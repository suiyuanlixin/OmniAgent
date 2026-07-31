from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent


def _source_checkout_root() -> Path | None:
    candidate = SRC_DIR.parent
    package_dir = candidate / "src" / "omniagent"
    if (candidate / "README.md").is_file() and package_dir == PACKAGE_DIR:
        return candidate
    return None


SOURCE_ROOT = _source_checkout_root()
PROJECT_ROOT = SOURCE_ROOT or PACKAGE_DIR

_configured_home = str(os.environ.get("OMNIAGENT_HOME") or "").strip()
if _configured_home:
    APP_HOME = Path(_configured_home).expanduser().resolve()
elif SOURCE_ROOT is not None:
    # Preserve existing local data locations when running from a source checkout.
    APP_HOME = SOURCE_ROOT
else:
    APP_HOME = (Path.home() / ".omniagent").resolve()
