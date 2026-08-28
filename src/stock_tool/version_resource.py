"""Generate the Windows version resource from StockTool's one canonical version."""

from __future__ import annotations

from pathlib import Path

from stock_tool import __version__


def windows_version_tuple(version: str = __version__) -> str:
    """Translate a canonical semantic version into a four-part Windows tuple."""

    pieces = version.split("-", maxsplit=1)[0].split("+", maxsplit=1)[0].split(".")
    if len(pieces) != 3 or any(not piece.isdigit() for piece in pieces):
        raise ValueError("Canonical version must contain three numeric components.")
    return ", ".join((*pieces, "0"))


def version_resource_text(version: str = __version__) -> str:
    """Return PyInstaller version-file content without a second hard-coded version."""

    windows_version = windows_version_tuple(version)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({windows_version}), prodvers=({windows_version}), mask=0x3f, flags=0x0, OS=0x4, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'StockTool Internal Test'),
        StringStruct('FileDescription', 'StockTool'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'StockTool'),
        StringStruct('OriginalFilename', 'StockTool.exe'),
        StringStruct('ProductName', 'StockTool'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write_version_resource(destination: Path, version: str = __version__) -> Path:
    """Write the generated PyInstaller resource to a build-only location."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(version_resource_text(version), encoding="utf-8")
    return destination
