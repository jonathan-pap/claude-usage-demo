"""
Validate generated files in machines/ before they are pushed to git.

Checks:
  - All .json files parse as JSON
  - No file (.json or .js) contains git conflict markers (<<<<<<<, =======, >>>>>>>)
  - manifest.json has a non-empty machines[] list

Exit code 0 = OK, 1 = at least one problem found (with details on stderr).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows so checkmark/cross glyphs don't crash cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
MACHINES = ROOT / "machines"
CONFLICT_RE = re.compile(r"^(<{7}\s|={7}$|>{7}\s)", re.MULTILINE)


def main() -> int:
    if not MACHINES.is_dir():
        print("  validate: no machines/ directory; nothing to check.")
        return 0

    errors: list[str] = []
    checked = 0

    for f in sorted(MACHINES.iterdir()):
        if not f.is_file():
            continue
        if f.suffix not in (".json", ".js"):
            continue
        checked += 1
        try:
            text = f.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"{f.name}: cannot read ({e})")
            continue

        if CONFLICT_RE.search(text):
            errors.append(f"{f.name}: contains git conflict markers")
            continue

        if f.suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                errors.append(f"{f.name}: invalid JSON at line {e.lineno} ({e.msg})")
                continue
            if f.name == "manifest.json":
                machines = data.get("machines") if isinstance(data, dict) else None
                if not machines:
                    errors.append("manifest.json: machines[] is empty or missing")
        elif f.suffix == ".js":
            # JS shims are 'window.X = <JSON>;\n' — parse the embedded JSON so
            # malformed JS (unbalanced braces, stray characters) is caught
            # before push, not at browser load time.
            import re
            m = re.match(r"\s*window\.[A-Za-z_][A-Za-z0-9_]*\s*=\s*", text)
            if not m:
                errors.append(f"{f.name}: doesn't match expected shim shape (window.X = ...;)")
                continue
            payload = text[m.end():].rstrip().rstrip(";").rstrip()
            try:
                json.loads(payload)
            except json.JSONDecodeError as e:
                errors.append(f"{f.name}: shim payload isn't valid JSON ({e.msg} at line {e.lineno})")

    if errors:
        print("  ✗ machine output validation failed:", file=sys.stderr)
        for e in errors:
            print(f"     - {e}", file=sys.stderr)
        return 1

    if checked == 0:
        # First run on a brand-new clone, before this machine's snapshot is
        # committed. Treat as a successful no-op — build_machine_snapshot.py
        # will populate machines/ momentarily.
        print("  ✓ machines/ is empty — first run on this machine; snapshot will be created.")
        return 0

    print(f"  ✓ {checked} machine file(s) validated (JSON parses, no conflict markers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
