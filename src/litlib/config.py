"""Yol ve ortam yapılandırması: taşınabilir çalışma dizini ve isteğe bağlı D sürücüsü depolama politikası."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_path

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _default_project_root() -> Path:
    if (SOURCE_ROOT / "pyproject.toml").exists():
        return SOURCE_ROOT
    return Path(user_data_path("litlib", appauthor=False))


PROJECT_ROOT = Path(os.environ.get("LITLIB_ROOT") or _default_project_root())


def _dotenv_setting(key: str) -> str:
    """Değişmez yolları kurabilmek için proje .env'inden tek bir değeri erkenden okur."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return ""
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


_DEFAULT_RUNTIME_ROOT = (
    Path("D:/LitLibRuntime")
    if PROJECT_ROOT.drive.upper() == "D:"
    else PROJECT_ROOT / ".litlib-runtime"
)
RUNTIME_ROOT = Path(
    os.environ.get("LITLIB_RUNTIME_ROOT")
    or _dotenv_setting("LITLIB_RUNTIME_ROOT")
    or _DEFAULT_RUNTIME_ROOT
)


@dataclass(frozen=True)
class Paths:
    project_root: Path = PROJECT_ROOT
    venv: Path = PROJECT_ROOT / ".venv"
    sqlite_dir: Path = PROJECT_ROOT / "state"
    sqlite_db: Path = PROJECT_ROOT / "state" / "litlib.db"
    staging_downloads: Path = PROJECT_ROOT / "staging" / "downloads"
    staging_supplements: Path = PROJECT_ROOT / "staging" / "supplements"
    output: Path = PROJECT_ROOT / "output"
    logs: Path = PROJECT_ROOT / "logs"
    data: Path = PROJECT_ROOT / "data"

    runtime_root: Path = RUNTIME_ROOT
    tmp: Path = RUNTIME_ROOT / "tmp"
    cache: Path = RUNTIME_ROOT / "cache"
    models: Path = RUNTIME_ROOT / "models"
    chrome_profile: Path = RUNTIME_ROOT / "chrome" / "profile"
    chrome_cache: Path = RUNTIME_ROOT / "chrome" / "cache"
    chrome_downloads: Path = RUNTIME_ROOT / "chrome" / "downloads"

    env_map: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "env_map", {
            "TEMP": str(self.tmp),
            "TMP": str(self.tmp),
            "UV_CACHE_DIR": str(self.cache / "uv"),
            "PIP_CACHE_DIR": str(self.cache / "pip"),
            "XDG_CACHE_HOME": str(self.cache),
            "HF_HOME": str(self.cache / "huggingface"),
            "TORCH_HOME": str(self.cache / "torch"),
            "NODE_COMPILE_CACHE": str(self.cache / "node"),
            "npm_config_cache": str(self.cache / "npm"),
            "PYTHONPYCACHEPREFIX": str(self.cache / "python"),
        })


def on_d_drive(path: Path | str) -> bool:
    """Yolun D sürücüsünde (ya da UNC Temp biriminde, yani geçerli Temp sürücüsünde) olup olmadığını belirler."""
    p = Path(path)
    try:
        drive = Path(p.anchor).resolve().drive or p.anchor
    except Exception:
        drive = ""
    return drive.upper().startswith("D:")


def require_d_drive() -> bool:
    """Büyük çıktı üreten komutların D:'de kalması gerekip gerekmediği; varsayılan bu klonun sürücüsüdür."""
    value = os.environ.get("LITLIB_REQUIRE_D_DRIVE") or _dotenv_setting("LITLIB_REQUIRE_D_DRIVE")
    if value:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return PROJECT_ROOT.drive.upper() == "D:"


def ensure_storage_path(path: Path | str) -> None:
    if require_d_drive() and not on_d_drive(path):
        raise ValueError(
            f"Depolama politikası D sürücüsüne yazmayı gerektiriyor, geçerli yol {Path(path)}; "
            "yolu değiştirin ya da açıkça LITLIB_REQUIRE_D_DRIVE=0 ayarlayın"
        )


def ensure_dirs(paths: Paths) -> None:
    dirs = [
        paths.sqlite_dir, paths.staging_downloads, paths.staging_supplements,
        paths.output, paths.logs,
        paths.data, paths.tmp, paths.cache, paths.models,
        paths.chrome_profile, paths.chrome_cache, paths.chrome_downloads,
        paths.runtime_root / "experience",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def load_dotenv(path: Path | str | None = None) -> None:
    """Proje .env dosyasını yükler (basit KEY=VALUE, üçüncü taraf bağımlılığı yok; zaten ayarlı olanların üzerine yazmaz)."""
    env_file = Path(path or (PROJECT_ROOT / ".env"))
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def ensure_runtime_env() -> None:
    """Çalışma zamanı ortam değişkenlerini süreç düzeyinde ayarlar (yalnız bu süreç, sistem geneli değişmez).

    Her CLI giriş noktasının TEMP/önbellek/model dizinlerinin LITLIB_RUNTIME_ROOT altında kalmasını sağlar,
    ardından kalan proje .env ayarlarını yükler.
    """
    for key, value in paths.env_map.items():
        os.environ[key] = value
    load_dotenv()


def cache_dirs() -> list[Path]:
    return [paths.cache / name for name in ("uv", "pip", "huggingface", "torch", "npm", "python")]


paths = Paths()
