"""
Build a per-machine aggregate snapshot for multi-machine sync.

Reads (from this script's directory):
  - usage_history.json (daily totals)
  - insights.json      (per-tool, per-project, per-MCP attribution)

Writes:
  - machines/<hostname>.json  (combined per-machine snapshot)

Updates:
  - machines/manifest.json    (lists all known machines)

The output contains ONLY metrics — no chat content, no file paths from JSONL bodies,
no commands. Safe to commit to a private GitHub repo.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MACHINES_DIR = ROOT / "machines"
MACHINES_DIR.mkdir(exist_ok=True)


def hostname_slug() -> str:
    # Prefer CCUSAGE_HOST when update_usage.sh exports it — keeps the bash
    # `hostname` and Python `socket.gethostname()` views aligned (they can
    # differ on Windows when one includes the AD domain and the other
    # doesn't, scattering snapshots across multiple files for one machine).
    forced = os.environ.get("CCUSAGE_HOST")
    if forced:
        return forced.lower().replace(" ", "-")
    h = socket.gethostname() or os.environ.get("COMPUTERNAME") or "unknown"
    return h.lower().replace(" ", "-")


def load_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  warn: failed to load {p.name}: {e}", file=sys.stderr)
        return None


def main() -> int:
    host = hostname_slug()
    history = load_json(ROOT / "usage_history.json")
    insights = load_json(ROOT / "insights.json")

    if history is None and insights is None:
        print("Neither usage_history.json nor insights.json found. Run update_usage.sh first.", file=sys.stderr)
        return 1

    snapshot = {
        "machine":     host,
        "platform":    platform.system().lower(),
        "platformVersion": platform.release(),
        # "user" field intentionally omitted — would expose OS username publicly.
        "lastUpdated": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "schemaVersion": 1,
    }

    if history is not None:
        snapshot["dailyTotals"] = history.get("totals", {})
        snapshot["daily"]       = history.get("daily", [])
        snapshot["snapshots"]   = history.get("snapshots", [])

    if insights is not None:
        # Strip any heavy / overly granular fields. Keep core attribution data.
        keep_keys = ("totals", "bySource", "byModel", "byProject", "byTool", "byMCPServer", "bySubagent", "filesScanned")
        ins = {k: insights[k] for k in keep_keys if k in insights}

        # Strip full filesystem paths from all sections so machine snapshots
        # committed to git never contain local paths or OS usernames.

        # byProject: remove the raw cwd field — project name is already stored separately.
        if "byProject" in ins:
            ins["byProject"] = [
                {k: v for k, v in p.items() if k != "cwd"}
                for p in ins["byProject"]
            ]

        # byTool and byMCPServer: the projects dict uses full filesystem paths as
        # keys (e.g. "C:\Users\jonathan\...": count). Replace each key with just
        # the final directory component so no local paths reach committed JSON.
        import posixpath as _pp

        def _basename(path: str) -> str:
            p = path.replace("\\", "/").rstrip("/")
            return _pp.basename(p) or path

        def _strip_project_paths(items):
            for item in (items or []):
                if isinstance(item, dict) and isinstance(item.get("projects"), dict):
                    item["projects"] = {_basename(k): v for k, v in item["projects"].items()}

        _strip_project_paths(ins.get("byTool"))
        _strip_project_paths(ins.get("byMCPServer"))

        snapshot["insights"] = ins
        # Slim hourly trend (just hour/cost/turns) so the timeline chart can
        # show all machines without bloating the snapshot.
        snapshot["hourlyTrend"] = [
            {"hour": h.get("hour"), "cost": round(float(h.get("cost") or 0), 4), "turns": int(h.get("turns") or 0)}
            for h in insights.get("hourlyTrend", []) if h.get("hour")
        ]

    out_path = MACHINES_DIR / f"{host}.json"
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    # Refresh manifest.json
    NON_MACHINE_FILES = {"manifest.json", "daily_merged.json", "hourly_merged.json", "all_machines.json"}
    machines = []
    for p in sorted(MACHINES_DIR.glob("*.json")):
        if p.name in NON_MACHINE_FILES:
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(m, dict):
                continue
            machines.append({
                "machine":      m.get("machine", p.stem),
                "file":         p.name,
                "platform":     m.get("platform", ""),
                "lastUpdated":  m.get("lastUpdated", ""),
                "totalCost":    (m.get("dailyTotals") or {}).get("totalCost", 0),
                "totalTokens":  (m.get("dailyTotals") or {}).get("totalTokens", 0),
                "daysCovered":  len(m.get("daily", [])),
                "insightsCost": (m.get("insights", {}).get("totals") or {}).get("cost", 0),
                "insightsTurns":(m.get("insights", {}).get("totals") or {}).get("turns", 0),
            })
        except Exception:
            continue

    manifest = {
        "schemaVersion":  1,
        "generatedAt":    datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "machineCount":   len(machines),
        "machines":       machines,
    }
    (MACHINES_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # JS shim for file:// usage
    (MACHINES_DIR / "manifest.js").write_text(
        "window.MACHINES_MANIFEST = " + json.dumps(manifest, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    # Cross-machine merged daily series (date -> summed cost across all machines).
    # Used by the heatmap so it shows the full multi-machine picture, not just
    # this machine's local insights.json.
    merged: dict[str, dict] = {}
    for p in sorted(MACHINES_DIR.glob("*.json")):
        if p.name in NON_MACHINE_FILES:
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(m, dict):
            continue
        host_name = m.get("machine", p.stem)
        for row in m.get("daily", []):
            date = row.get("date")
            if not date:
                continue
            cost = float(row.get("totalCost") or 0)
            entry = merged.setdefault(date, {"date": date, "cost": 0.0, "byMachine": {}})
            entry["cost"] += cost
            entry["byMachine"][host_name] = round(cost, 4)
    merged_list = [
        {"date": v["date"], "cost": round(v["cost"], 4), "byMachine": v["byMachine"]}
        for v in sorted(merged.values(), key=lambda x: x["date"])
    ]
    (MACHINES_DIR / "daily_merged.js").write_text(
        "window.DAILY_MERGED = " + json.dumps(merged_list, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    (MACHINES_DIR / "daily_merged.json").write_text(
        json.dumps(merged_list, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Cross-machine merged hourly series (same idea, hour-level).
    hourly_merged: dict[str, dict] = {}
    for p in sorted(MACHINES_DIR.glob("*.json")):
        if p.name in NON_MACHINE_FILES:
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(m, dict):
            continue
        host_name = m.get("machine", p.stem)
        for row in m.get("hourlyTrend", []):
            hour = row.get("hour")
            if not hour:
                continue
            cost  = float(row.get("cost") or 0)
            turns = int(row.get("turns") or 0)
            entry = hourly_merged.setdefault(hour, {"hour": hour, "cost": 0.0, "turns": 0, "byMachine": {}})
            entry["cost"]  += cost
            entry["turns"] += turns
            entry["byMachine"][host_name] = round(cost, 4)
    hourly_list = [
        {"hour": v["hour"], "cost": round(v["cost"], 4), "turns": v["turns"], "byMachine": v["byMachine"]}
        for v in sorted(hourly_merged.values(), key=lambda x: x["hour"])
    ]
    (MACHINES_DIR / "hourly_merged.js").write_text(
        "window.HOURLY_MERGED = " + json.dumps(hourly_list, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    (MACHINES_DIR / "hourly_merged.json").write_text(
        json.dumps(hourly_list, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Bundle every machine's daily[] under one shim so dashboards can read
    # cross-machine daily data without fetching individual JSON files
    # (browsers block fetch under file://). Per-machine totals are kept
    # separate so the dashboard's Machine filter can switch between hosts.
    all_machines: dict[str, dict] = {}
    for p in sorted(MACHINES_DIR.glob("*.json")):
        if p.name in NON_MACHINE_FILES:
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(m, dict):
            continue
        host_name = m.get("machine", p.stem)
        all_machines[host_name] = {
            "platform":    m.get("platform", ""),
            "lastUpdated": m.get("lastUpdated", ""),
            "totals":      m.get("dailyTotals") or {},
            "daily":       m.get("daily", []),
        }
    (MACHINES_DIR / "all_machines.js").write_text(
        "window.ALL_MACHINES = " + json.dumps(all_machines, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    (MACHINES_DIR / "all_machines.json").write_text(
        json.dumps(all_machines, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Wrote {out_path.name} for machine '{host}'")
    print(f"  daily totals: ${snapshot.get('dailyTotals', {}).get('totalCost', 0):.2f} over {len(snapshot.get('daily', []))} days")
    print(f"  insights:     ${snapshot.get('insights', {}).get('totals', {}).get('cost', 0):.2f} across {snapshot.get('insights', {}).get('totals', {}).get('turns', 0)} turns")
    print(f"Manifest now lists {len(machines)} machine(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
