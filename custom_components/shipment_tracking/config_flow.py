"""Config & options flow — assembled from _config_flow_part*.py fragments.

Fragments exist because GitHub MCP push payloads are size-limited; they are
concatenated at import time into this module's namespace. Prefer re-merging
to a single config_flow.py before merge if desired.
"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent
_src = "".join(
    (_DIR / f"_config_flow_part{i}.py").read_text(encoding="utf-8")
    for i in range(4)
)
exec(compile(_src, str(_DIR / "config_flow.py"), "exec"), globals())
