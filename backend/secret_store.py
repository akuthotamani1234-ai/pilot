"""Encrypted storage for a test account the tester created (only when you allowed it for that run).

  accounts/<site>.json  ->  user name in plain text, password ENCRYPTED.
  Windows: DPAPI (CryptProtectData) - only your Windows user on this PC can decrypt it; copying the file to
  another PC or user is useless. Other systems: no OS encryption available without extra packages, so the file is
  made readable by your user only (chmod 600) and the report says so.
Passwords you type in the web UI are never stored at all: they live in memory for that one run.
"""
import base64
import json
import os
import sys
from pathlib import Path

ACCOUNTS = Path("accounts")
_ENTROPY = b"agentic-qa test account v1"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    src = ctypes.create_string_buffer(data, len(data))
    ent = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    blob_in = Blob(len(data), ctypes.cast(src, ctypes.c_void_p))
    blob_ent = Blob(len(_ENTROPY), ctypes.cast(ent, ctypes.c_void_p))
    blob_out = Blob()
    ui_forbidden = 0x1
    if not fn(ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None, ui_forbidden, ctypes.byref(blob_out)):
        raise OSError("Windows could not " + ("encrypt" if protect else "decrypt") + " the saved test account")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(text: str) -> tuple[str, str]:
    """-> (stored value, method)."""
    if sys.platform == "win32":
        return base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii"), "dpapi"
    return text, "plain-600"


def unprotect(value: str, method: str) -> str:
    if method == "dpapi":
        return _dpapi(base64.b64decode(value), False).decode("utf-8")
    return value


def save_account(site_key: str, account: dict, folder: Path = ACCOUNTS) -> Path:
    """Save a created test account. The password is encrypted; nothing else is secret."""
    folder.mkdir(exist_ok=True)
    secret, method = protect(account["password"])
    data = {k: v for k, v in account.items() if k != "password"}
    data.update(secret=secret, protection=method)
    f = folder / f"{site_key}.json"
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if method != "dpapi":
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f


def load_account(site_key: str, folder: Path = ACCOUNTS) -> dict | None:
    """The saved account with its password decrypted (in memory only), or None."""
    f = folder / f"{site_key}.json"
    try:
        a = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        if a.get("secret"):
            a["password"] = unprotect(a.pop("secret"), a.pop("protection", "dpapi"))
        elif a.get("password"):  # an old file from before encryption: encrypt it now
            save_account(site_key, a, folder)
    except (OSError, ValueError):
        return None  # made by another Windows user / PC: can't be used
    return a if a.get("username") and a.get("password") else None
