from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "gateway_lite", ROOT / "ros_bridge_lite"]

bad = []
for base in TARGETS:
    for p in base.rglob("*.py"):
        txt = p.read_text(encoding="utf-8")
        if "import nanobot" in txt or "from nanobot" in txt:
            bad.append(p)

if bad:
    print("FAILED: found nanobot imports")
    for p in bad:
        print(" -", p)
    raise SystemExit(1)

print("OK: no nanobot runtime imports found")
