"""吉大 WebVPN 机构通道：专用 Chrome + CDP（并发 1，有监督小批量）。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import websockets

from litlib.config import paths

logger = logging.getLogger("litlib.chrome_cdp")

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
DELAY_SECONDS = (8, 15)
DOWNLOAD_DIR = paths.chrome_downloads
SESSION_FILE = paths.sqlite_dir / "chrome_session.json"


@dataclass
class ChromeSession:
    proc: subprocess.Popen | None = None

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc:
            SESSION_FILE.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, errors="ignore", timeout=5,
            )
            return str(pid) in result.stdout
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _load_owned_session() -> dict | None:
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
        if pid and _pid_alive(pid):
            return data
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        pass
    SESSION_FILE.unlink(missing_ok=True)
    return None


def _cdp_available() -> bool:
    try:
        with httpx.Client(timeout=2) as client:
            return client.get(f"http://{CDP_HOST}:{CDP_PORT}/json/version").status_code == 200
    except httpx.HTTPError:
        return False


def find_chrome() -> str | None:
    for p in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ):
        if p.exists():
            return str(p)
    return shutil.which("chrome") or shutil.which("msedge")


def launch_chrome() -> ChromeSession:
    owned = _load_owned_session()
    if _cdp_available():
        if owned:
            logger.info("复用专用 Chrome（pid=%s）", owned["pid"])
            return ChromeSession()
        raise RuntimeError(
            f"CDP 端口 {CDP_PORT} 已被非 litlib 浏览器占用；为避免操作错误会话，请先关闭该实例。")
    if owned:
        raise RuntimeError(
            "检测到 litlib 专用 Chrome 进程仍在运行但 CDP 无响应；请手动关闭该窗口后重试。")
    exe = find_chrome()
    if not exe:
        raise FileNotFoundError("未找到 Chrome/Edge")
    paths.chrome_profile.mkdir(parents=True, exist_ok=True)
    paths.chrome_cache.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        exe,
        f"--user-data-dir={paths.chrome_profile}",
        f"--disk-cache-dir={paths.chrome_cache}",
        f"--remote-debugging-address={CDP_HOST}",
        f"--remote-debugging-port={CDP_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "about:blank",
    ]
    logger.info("启动专用 Chrome（profile=%s, CDP 127.0.0.1:%s）", paths.chrome_profile, CDP_PORT)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({
        "pid": proc.pid,
        "profile": str(paths.chrome_profile),
        "port": CDP_PORT,
    }), encoding="utf-8")
    return ChromeSession(proc=proc)


async def wait_for_cdp(timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"http://{CDP_HOST}:{CDP_PORT}/json/version")
                if r.status_code == 200:
                    return r.json()["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError(f"CDP 端口 {CDP_PORT} 无响应（Chrome 未启动？）")


async def browser_ws_url() -> str:
    """返回 browser-level WebSocket 地址（/json/version）。"""
    return await wait_for_cdp(10)


async def close_browser() -> None:
    """显式关闭 CDP 专用浏览器。"""
    if not _load_owned_session():
        raise RuntimeError("没有可验证归属的 litlib 专用浏览器")
    bws = await browser_ws_url()
    async with websockets.connect(bws, max_size=50 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
        try:
            await asyncio.wait_for(ws.recv(), timeout=5)
        except Exception:
            pass
    SESSION_FILE.unlink(missing_ok=True)


async def create_tab_navigate(url: str, timeout: float = 60.0) -> str | None:
    """用 browser-level Target.createTarget 开新标签并导航，返回新标签 page WS URL。

    /json/new 在本版本 Chrome 已失效，必须走 browser session。
    """
    bws = await browser_ws_url()
    async with websockets.connect(bws, max_size=50 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": url}}))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == 1:
                break
        target_id = resp.get("result", {}).get("targetId", "")
        if not target_id:
            return None
    # 轮询 /json/list 找到该 target
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"http://{CDP_HOST}:{CDP_PORT}/json/list")
            for page in r.json():
                if page.get("type") == "page" and page.get("id") == target_id:
                    return page.get("webSocketDebuggerUrl")
        await asyncio.sleep(1.0)
    return None


class Tab:
    def __init__(self, ws_url: str):
        self._ws_url = ws_url
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._msg_id = 0
        self._events: list[dict] = []

    async def connect(self) -> None:
        self._ws = await websockets.connect(self._ws_url, max_size=50 * 1024 * 1024)

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()

    async def close_target(self) -> None:
        """关闭当前页面 target；失败时至少断开调试连接。"""
        try:
            if self._ws:
                await self.cmd("Page.close")
        except Exception:
            pass
        finally:
            await self.close()

    def drain_events(self) -> list[dict]:
        evts, self._events = self._events, []
        return evts

    async def cmd(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        msg_id = self._msg_id
        await self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            resp = json.loads(await self._ws.recv())
            if resp.get("id") == msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP {method} 失败: {resp['error']}")
                return resp.get("result", {})
            self._events.append(resp)


async def new_tab(client: httpx.AsyncClient, url: str) -> Tab:
    ws = await create_tab_navigate(url, timeout=30)
    if not ws:
        raise RuntimeError("无法创建浏览器标签页")
    return Tab(ws)


async def set_download_dir(tab: Tab, download_dir: Path) -> None:
    await tab.cmd("Browser.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": str(download_dir),
        "eventsEnabled": True,
    })


async def navigate(tab: Tab, url: str, timeout: float = 60.0) -> None:
    await tab.cmd("Page.enable")
    await tab.cmd("Page.navigate", {"url": url})


async def page_title(tab: Tab) -> str:
    """读取当前页标题（识别验证码/拦截页等）。"""
    try:
        r = await tab.cmd("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
        return str(r.get("result", {}).get("value", ""))[:80]
    except Exception:
        return "<title 读取失败>"


async def dismiss_cookie_banner(tab: Tab) -> str:
    """尝试点击 'Accept all cookies' 类横幅按钮，返回点击结果描述。"""
    js = r'''
    (() => {
      const els = [...document.querySelectorAll('button, a, [role="button"]')];
      for (const e of els) {
        const t = (e.textContent || '').trim().toLowerCase();
        if (t && t.length < 40 && /accept.*cookies|接受.*cookie|同意.*cookie/.test(t)) {
          e.click();
          return 'clicked: ' + t.slice(0, 40);
        }
      }
      return 'no banner';
    })()
    '''
    try:
        r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return str(r.get("result", {}).get("value", ""))
    except Exception as e:
        return f"banner err: {e}"


async def click_pdf_link(tab: Tab) -> str:
    """查找并点击落地页上的 PDF 下载链接，返回点击信息或 'none'。"""
    js = r'''
    (() => {
      const anchors = [...document.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]')];
      const norm = (s) => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
      const cand = anchors.filter(a => {
        const t = norm(a.textContent || a.value);
        const href = norm(a.href);
        if (!href) return false;
        if (href.startsWith('javascript')) return false;
        if (/\.pdf([?#]|$)/.test(href)) return true;
        if (/(articlepdf|downloadpdf|pdfdownload|doi\/pdf|\/pdf\/)/.test(href)) return true;
        if (t && t.length < 60 && /\b(download|view|get|article|full)?.?(pdf|article pdf|pdf download)\b/.test(t)) return true;
        return false;
      });
      if (!cand.length) return 'none';
      const a = cand[0];
      const info = (a.textContent || a.value || '').trim().slice(0, 30) + ' | ' + (a.href || '').slice(0, 140);
      a.click();
      return 'clicked: ' + info;
    })()
    '''
    try:
        r = await tab.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return str(r.get("result", {}).get("value", ""))
    except Exception as e:
        return f"click err: {e}"


async def close_extra_tabs(client: httpx.AsyncClient, keep_url: str = "") -> None:
    """保留 keep_url 页签，关闭其余（含 about:blank）。"""
    r = await client.get(f"http://{CDP_HOST}:{CDP_PORT}/json/list", timeout=10)
    r.raise_for_status()
    for page in r.json():
        if page.get("type") != "page":
            continue
        if keep_url and keep_url in page.get("url", ""):
            continue
        try:
            await client.get(f"http://{CDP_HOST}:{CDP_PORT}/json/close/{page['id']}", timeout=10)
        except Exception:
            pass


def wait_for_download_file(download_dir: Path, timeout: float = 120.0,
                           min_size: int = 1024, seen: set[Path] | None = None) -> Path | None:
    """轮询下载目录中相对已有集合新增的完成 PDF。"""
    seen = seen or set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        crdownloads = list(download_dir.glob("*.crdownload"))
        if not crdownloads:
            files = sorted(
                (f for f in download_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"),
                key=lambda f: f.stat().st_mtime,
            )
            for f in files:
                if f not in seen and f.stat().st_size >= min_size:
                    seen.add(f)
                    return f
        time.sleep(1.0)
    return None
