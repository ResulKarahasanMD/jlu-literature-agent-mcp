"""机构账号凭证与敏感数据保护（Windows 原生，零第三方依赖）。

- 账号密码：Windows 凭据管理器（CredWrite/CredRead），系统级加密，
  仅当前 Windows 用户可读，不落盘明文。
- 会话 cookie 备份：DPAPI（CryptProtectData）加密文件，密钥绑定当前用户。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

# Credential Manager and DPAPI exist only on Windows. Elsewhere (macOS BVU/GlobalProtect
# setup) no institution password is used: reads report "no credential", writes fail loudly.
IS_WINDOWS = os.name == "nt"


def _require_windows(feature: str) -> None:
    if not IS_WINDOWS:
        raise OSError(f"{feature} is only available on Windows")

# ---- Windows 凭据管理器 -------------------------------------------------

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


def save_cred(service: str, username: str, password: str) -> None:
    _require_windows("Credential Manager")
    blob = (ctypes.c_byte * len(password.encode("utf-16-le")))(
        *password.encode("utf-16-le")
    )
    cred = CREDENTIAL(
        Flags=0,
        Type=CRED_TYPE_GENERIC,
        TargetName=service,
        Comment="litlib 机构登录凭证",
        CredentialBlobSize=len(password.encode("utf-16-le")),
        CredentialBlob=blob,
        Persist=CRED_PERSIST_LOCAL_MACHINE,
        UserName=username,
    )
    ok = ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0)
    if not ok:
        raise OSError(f"CredWriteW 失败: {ctypes.get_last_error()}")


def load_cred(service: str) -> tuple[str, str] | None:
    if not IS_WINDOWS:
        return None
    handle = ctypes.c_void_p()
    ok = ctypes.windll.advapi32.CredReadW(
        service, CRED_TYPE_GENERIC, 0, ctypes.byref(handle)
    )
    if not ok:
        return None
    try:
        cred = ctypes.cast(handle, ctypes.POINTER(CREDENTIAL)).contents
        username = cred.UserName or ""
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        password = raw.decode("utf-16-le")
        return username, password
    finally:
        ctypes.windll.advapi32.CredFree(handle)


def delete_cred(service: str) -> bool:
    if not IS_WINDOWS:
        return False
    ok = ctypes.windll.advapi32.CredDeleteW(service, CRED_TYPE_GENERIC, 0)
    return bool(ok)


# ---- DPAPI 文件加密 ------------------------------------------------------

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    _require_windows("DPAPI")
    in_blob = DATA_BLOB(len(data), ctypes.cast(
        ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    flags = CRYPTPROTECT_UI_FORBIDDEN if protect else 0
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(in_blob), None, None, None, None, flags, ctypes.byref(out_blob))
    if not ok:
        raise OSError(f"DPAPI 失败: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def encrypt_file(src_bytes: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_dpapi(src_bytes, protect=True))


def decrypt_file(src: Path) -> bytes:
    return _dpapi(src.read_bytes(), protect=False)


# ---- 便捷接口 ------------------------------------------------------------

SERVICE_ID = "litlib/jlu-institution"

SESSION_COOKIE_FILE = None  # 由 config 注入


def save_institution_cred(username: str, password: str) -> None:
    save_cred(SERVICE_ID, username, password)


def load_institution_cred() -> tuple[str, str] | None:
    return load_cred(SERVICE_ID)


def has_institution_cred() -> bool:
    return load_institution_cred() is not None
