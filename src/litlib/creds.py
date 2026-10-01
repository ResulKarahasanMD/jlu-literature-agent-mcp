"""Kurum hesabı kimlik bilgileri ve hassas veri koruması (Windows yerel API'leri, sıfır üçüncü taraf bağımlılığı).

- Hesap parolası: Windows Kimlik Bilgisi Yöneticisi (CredWrite/CredRead), sistem düzeyinde şifreli,
  yalnız geçerli Windows kullanıcısı okuyabilir, diske düz metin yazılmaz.
- Oturum çerezi yedeği: DPAPI (CryptProtectData) ile şifreli dosya, anahtar geçerli kullanıcıya bağlı.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

# Kimlik Bilgisi Yöneticisi ve DPAPI yalnız Windows'ta var. Başka yerde (macOS BVU/GlobalProtect
# kurulumu) kurum parolası kullanılmaz: okumalar "kimlik bilgisi yok" döner, yazmalar açıkça hata verir.
IS_WINDOWS = os.name == "nt"


def _require_windows(feature: str) -> None:
    if not IS_WINDOWS:
        raise OSError(f"{feature} is only available on Windows")

# ---- Windows Kimlik Bilgisi Yöneticisi---------------------------------------

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
        Comment="litlib kurum girişi kimlik bilgisi",
        CredentialBlobSize=len(password.encode("utf-16-le")),
        CredentialBlob=blob,
        Persist=CRED_PERSIST_LOCAL_MACHINE,
        UserName=username,
    )
    ok = ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0)
    if not ok:
        raise OSError(f"CredWriteW başarısız: {ctypes.get_last_error()}")


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


# ---- DPAPI dosya şifreleme ----------------------------------------------

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
        raise OSError(f"DPAPI başarısız: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def encrypt_file(src_bytes: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_dpapi(src_bytes, protect=True))


def decrypt_file(src: Path) -> bytes:
    return _dpapi(src.read_bytes(), protect=False)


# ---- Kolaylık arayüzü--------------------------------------------------------

SERVICE_ID = "litlib/jlu-institution"

SESSION_COOKIE_FILE = None  # config tarafından atanır


def save_institution_cred(username: str, password: str) -> None:
    save_cred(SERVICE_ID, username, password)


def load_institution_cred() -> tuple[str, str] | None:
    return load_cred(SERVICE_ID)


def has_institution_cred() -> bool:
    return load_institution_cred() is not None
