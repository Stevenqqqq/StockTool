"""Load the explicitly configured local Groq credential on Windows.

The setup command stores ``ConvertFrom-SecureString`` output in a fixed,
private location.  This module only reads that file when
``load_groq_key`` is called; importing it never discovers credentials or
touches the filesystem.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
from typing import Callable

__all__ = ["CredentialLoadError", "load_groq_key"]

_KEY_RELATIVE_PATH = Path("StockTool") / "secrets" / "groq-key.dpapi"
_MAX_FILE_BYTES = 131_072
_MAX_BLOB_BYTES = _MAX_FILE_BYTES // 2
_MAX_PLAINTEXT_BYTES = 65_536
_MAX_KEY_CHARS = 4_096
_HEX_RE = re.compile(rb"[0-9A-Fa-f]+")
_OUTER_TEXT_WHITESPACE = b" \t\r\n"
_Decryptor = Callable[[bytes | bytearray], bytes | bytearray]


class CredentialLoadError(RuntimeError):
    """A safe, user-facing failure while loading the local credential."""


def load_groq_key() -> str:
    """Load the StockTool-only Groq key from the Windows DPAPI file.

    The function has no environment or credential fallback.  In particular,
    it does not inspect generic API-key variables, project files, or other
    provider settings.
    """

    if os.name != "nt":
        raise CredentialLoadError("本機 Groq 金鑰不可用：此功能僅支援 Windows DPAPI。")
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise CredentialLoadError("本機 Groq 金鑰不可用：尚未設定本機安全儲存位置。")
    return _load_from_path(
        Path(local_app_data) / _KEY_RELATIVE_PATH,
        is_windows=True,
        decryptor=None,
    )


def _load_from_path(
    path: Path,
    *,
    is_windows: bool,
    decryptor: _Decryptor | None,
) -> str:
    """Load one path for tests and for the public fixed-path entry point."""

    if not is_windows:
        raise CredentialLoadError("本機 Groq 金鑰不可用：此功能僅支援 Windows DPAPI。")
    try:
        with path.open("rb") as handle:
            encoded = handle.read(_MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        raise CredentialLoadError("本機 Groq 金鑰不可用：尚未建立本機憑證。") from None
    except OSError:
        raise CredentialLoadError("本機 Groq 金鑰不可用：無法讀取本機憑證。") from None

    if len(encoded) > _MAX_FILE_BYTES:
        raise CredentialLoadError("本機 Groq 金鑰不可用：本機憑證大小無效。")
    try:
        encrypted = _decode_hex_blob(encoded)
    except ValueError:
        raise CredentialLoadError("本機 Groq 金鑰不可用：本機憑證格式無效。") from None
    if len(encrypted) > _MAX_BLOB_BYTES:
        raise CredentialLoadError("本機 Groq 金鑰不可用：本機憑證大小無效。")

    plaintext: bytes | bytearray | None = None
    try:
        plaintext = (decryptor or _decrypt_windows_dpapi)(encrypted)
        key = _decode_key(plaintext)
    except CredentialLoadError:
        raise
    except Exception:
        raise CredentialLoadError("本機 Groq 金鑰不可用：無法解密本機憑證。") from None
    finally:
        _zero_bytes(encrypted)
        if plaintext is not None:
            _zero_bytes(plaintext)
    return key


def _decode_hex_blob(encoded: bytes) -> bytearray:
    """Decode PowerShell's UTF-8 text representation of a DPAPI blob."""

    value = encoded
    if value.startswith(b"\xef\xbb\xbf"):
        value = value[3:]
    value = value.strip(_OUTER_TEXT_WHITESPACE)
    if not value or len(value) % 2 or not _HEX_RE.fullmatch(value):
        raise ValueError("invalid DPAPI hex")
    decoded = bytearray(bytes.fromhex(value.decode("ascii")))
    if not decoded or len(decoded) > _MAX_BLOB_BYTES:
        _zero_bytes(decoded)
        raise ValueError("invalid DPAPI size")
    return decoded


def _decode_key(plaintext: bytes | bytearray) -> str:
    """Decode the UTF-16LE SecureString payload and reject unsafe values."""

    if not plaintext or len(plaintext) > _MAX_PLAINTEXT_BYTES or len(plaintext) % 2:
        raise ValueError("invalid plaintext size")
    key = bytes(plaintext).decode("utf-16-le", errors="strict")
    if not 0 < len(key) <= _MAX_KEY_CHARS:
        raise ValueError("invalid key length")
    if any(character.isspace() or not character.isprintable() for character in key):
        raise ValueError("invalid key characters")
    return key


def _decrypt_windows_dpapi(ciphertext: bytes | bytearray) -> bytearray:
    """Decrypt one DPAPI blob and clear native buffers on every exit path."""

    if os.name != "nt":
        raise OSError("DPAPI is unavailable")

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    unprotect.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    input_buffer = (ctypes.c_ubyte * len(ciphertext)).from_buffer_copy(ciphertext)
    input_blob = _DataBlob(
        len(ciphertext), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    output_blob = _DataBlob()
    plaintext: bytearray | None = None
    try:
        if not unprotect(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise OSError("DPAPI decrypt failed")
        size = int(output_blob.cbData)
        if not output_blob.pbData or not 0 < size <= _MAX_PLAINTEXT_BYTES:
            raise OSError("DPAPI plaintext size invalid")
        plaintext = bytearray(ctypes.string_at(output_blob.pbData, size))
        return plaintext
    finally:
        ctypes.memset(ctypes.addressof(input_buffer), 0, len(input_buffer))
        if output_blob.pbData and output_blob.cbData:
            ctypes.memset(output_blob.pbData, 0, int(output_blob.cbData))
        if output_blob.pbData:
            local_free(output_blob.pbData)


def _zero_bytes(value: bytes | bytearray) -> None:
    """Best-effort clearing for mutable buffers held by this module."""

    if isinstance(value, bytearray):
        value[:] = b"\x00" * len(value)
