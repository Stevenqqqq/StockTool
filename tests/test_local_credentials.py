from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path

import pytest

from stock_tool.research import local_credentials
from stock_tool.research.local_credentials import CredentialLoadError


def _write_hex(path: Path, value: bytes, *, bom: bool = False) -> None:
    prefix = b"\xef\xbb\xbf" if bom else b""
    path.write_bytes(prefix + value.hex().encode("ascii") + b"\r\n")


def test_public_entrypoint_uses_fixed_localappdata_path(
    monkeypatch, tmp_path: Path
) -> None:
    calls = []

    def fake_load(path: Path, *, is_windows: bool, decryptor) -> str:
        calls.append((path, is_windows, decryptor))
        return "gsk_test_key"

    monkeypatch.setattr(local_credentials.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(local_credentials, "_load_from_path", fake_load)
    assert local_credentials.load_groq_key() == "gsk_test_key"
    assert calls == [
        (
            tmp_path / "StockTool" / "secrets" / "groq-key.dpapi",
            True,
            None,
        )
    ]


def test_missing_file_is_safe_and_does_not_echo_path(tmp_path: Path) -> None:
    path = tmp_path / "CANARY_PATH" / "groq-key.dpapi"
    with pytest.raises(CredentialLoadError) as error:
        local_credentials._load_from_path(
            path, is_windows=True, decryptor=lambda _: b"x"
        )
    assert "CANARY_PATH" not in str(error.value)
    assert "本機憑證" in str(error.value)


def test_non_windows_is_rejected_without_reading_file(tmp_path: Path) -> None:
    path = tmp_path / "credential.dpapi"
    path.write_bytes(b"00")
    with pytest.raises(CredentialLoadError) as error:
        local_credentials._load_from_path(
            path, is_windows=False, decryptor=lambda _: b"x"
        )
    assert "credential.dpapi" not in str(error.value)
    assert "Windows" in str(error.value)


@pytest.mark.parametrize(
    "encoded",
    [b"", b"0", b"GG", b"00 11", b"00\x00", b"\xef\xbb\xbf"],
)
def test_invalid_hex_is_rejected_without_echoing_content(
    tmp_path: Path, encoded: bytes
) -> None:
    path = tmp_path / "credential.dpapi"
    path.write_bytes(encoded)
    with pytest.raises(CredentialLoadError) as error:
        local_credentials._load_from_path(
            path, is_windows=True, decryptor=lambda _: b"x"
        )
    assert "本機憑證格式無效" in str(error.value)
    assert "GG" not in str(error.value)


def test_oversize_file_is_rejected_before_decrypt(tmp_path: Path) -> None:
    path = tmp_path / "credential.dpapi"
    path.write_bytes(b"0" * (local_credentials._MAX_FILE_BYTES + 1))
    called = False

    def decryptor(_: bytes | bytearray) -> bytes:
        nonlocal called
        called = True
        return b"x"

    with pytest.raises(CredentialLoadError):
        local_credentials._load_from_path(path, is_windows=True, decryptor=decryptor)
    assert called is False


def test_decrypt_error_is_sanitized(tmp_path: Path) -> None:
    path = tmp_path / "credential.dpapi"
    _write_hex(path, b"ciphertext")

    def decryptor(_: bytes | bytearray) -> bytes:
        raise RuntimeError("CANARY_SECRET")

    with pytest.raises(CredentialLoadError) as error:
        local_credentials._load_from_path(path, is_windows=True, decryptor=decryptor)
    assert "CANARY_SECRET" not in str(error.value)
    assert "credential.dpapi" not in str(error.value)


def test_fake_decryptor_accepts_utf16le_and_bom(tmp_path: Path) -> None:
    path = tmp_path / "credential.dpapi"
    _write_hex(path, b"ciphertext", bom=True)
    assert (
        local_credentials._load_from_path(
            path,
            is_windows=True,
            decryptor=lambda ciphertext: bytearray("gsk_test_key".encode("utf-16-le")),
        )
        == "gsk_test_key"
    )


@pytest.mark.parametrize("key", ["gsk bad", "gsk\nkey", "gsk\x00key"])
def test_decrypted_key_rejects_whitespace_and_control(tmp_path: Path, key: str) -> None:
    path = tmp_path / "credential.dpapi"
    _write_hex(path, b"ciphertext")
    with pytest.raises(CredentialLoadError) as error:
        local_credentials._load_from_path(
            path,
            is_windows=True,
            decryptor=lambda _: key.encode("utf-16-le"),
        )
    assert "CANARY" not in str(error.value)


def _protect_dpapi(value: bytes) -> bytes:
    """Create synthetic DPAPI data for the Windows-only round-trip test."""

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    protect.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    input_buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    input_blob = _DataBlob(
        len(value), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    output_blob = _DataBlob()
    try:
        assert protect(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
        return bytes(ctypes.string_at(output_blob.pbData, output_blob.cbData))
    finally:
        ctypes.memset(ctypes.addressof(input_buffer), 0, len(input_buffer))
        if output_blob.pbData and output_blob.cbData:
            ctypes.memset(output_blob.pbData, 0, int(output_blob.cbData))
        if output_blob.pbData:
            local_free(output_blob.pbData)


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is required")
def test_synthetic_windows_dpapi_roundtrip_in_temp(tmp_path: Path) -> None:
    path = tmp_path / "groq-key.dpapi"
    _write_hex(path, _protect_dpapi("gsk_synthetic_only".encode("utf-16-le")), bom=True)
    assert (
        local_credentials._load_from_path(path, is_windows=True, decryptor=None)
        == "gsk_synthetic_only"
    )
