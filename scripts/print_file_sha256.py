from __future__ import annotations

import argparse
from pathlib import Path

from stock_tool.release_manifest import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a file SHA-256 digest.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(sha256_file(args.path).upper())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
