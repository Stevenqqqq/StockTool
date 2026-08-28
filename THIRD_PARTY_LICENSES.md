# Third-Party License Inventory

This inventory is generated and verified from installed Python distribution
metadata by `scripts/generate_sbom.py`; the machine-readable SBOM is the
authoritative version-and-license record for a candidate environment. Do not
guess a license from a package name.

| Direct runtime dependency | Declared project constraint | License source |
| --- | --- | --- |
| openpyxl | `>=3.1.0` | Installed distribution metadata (MIT) |
| pandas | `>=2.2.0` | Installed distribution metadata (BSD-3-Clause text) |
| pypdf | `>=5.0.0` | Installed distribution metadata / bundled license files |
| streamlit | `>=1.36.0` | Installed distribution metadata / bundled license files |
| yfinance | `>=0.2.40` | Installed distribution metadata (Apache) |

Build and test tools, including PyInstaller, are also recorded in the SBOM when
present. PyInstaller's GPL exception must be reviewed before any public
distribution. This document is an inventory aid, not a substitute for the
license text distributed by each dependency.
