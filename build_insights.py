"""
Build insights.json from local Claude Code JSONL session logs.

Walks both:
  - $USERPROFILE/.claude/projects/  (CLI sessions)
  - %APPDATA%/Claude/local-agent-mode-sessions/.../local_*/.claude/projects/  (Cowork sessions)

Aggregates per-project, per-tool, per-MCP-server, per-subagent breakdowns.
Outputs insights.json next to this script — no chat content, only metrics.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Pricing per million tokens (USD) — Anthropic published rates
RATES = {
    "opus":   {"input": 5.0,  "output": 25.0, "cache_write_5m": 6.25, "cache_read": 0.50},
    "sonnet": {"input": 3.0,  "output": 15.0, "cache_write_5m": 3.75, "cache_read": 0.30},
    "haiku":  {"input": 1.0,  "output": 5.0,  "cache_write_5m": 1.25, "cache_read": 0.10},
}


def model_family(name: str) -> str:
    n = (name or "").lower()
    if "opus" in n: return "opus"
    if "sonnet" in n: return "sonnet"
    if "haiku" in n: return "haiku"
    return "sonnet"  # default fallback


def cost_for(model: str, usage: dict) -> float:
    r = RATES[model_family(model)]
    return (
        usage.get("input_tokens", 0)              * r["input"]          / 1e6
        + usage.get("output_tokens", 0)           * r["output"]         / 1e6
        + usage.get("cache_creation_input_tokens", 0) * r["cache_write_5m"] / 1e6
        + usage.get("cache_read_input_tokens", 0) * r["cache_read"]     / 1e6
    )


def discover_jsonl_files() -> list[tuple[Path, str]]:
    """Return list of (path, source) tuples. source is 'cli' or 'cowork'."""
    files: list[tuple[Path, str]] = []

    # CLI sessions
    cli_root = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".claude" / "projects"
    if cli_root.exists():
        for p in cli_root.rglob("*.jsonl"):
            files.append((p, "cli"))

    # Cowork sessions
    appdata = os.environ.get("APPDATA")
    if appdata:
        cowork_root = Path(appdata) / "Claude" / "local-agent-mode-sessions"
        if cowork_root.exists():
            for p in cowork_root.rglob("*.jsonl"):
                # skip audit.jsonl files (cowork session metadata, not CC logs)
                if p.name == "audit.jsonl":
                    continue
                if "/.claude/projects/" in p.as_posix() or "\\.claude\\projects\\" in str(p):
                    files.append((p, "cowork"))

    return files


def project_name_from_cwd(cwd: str) -> str:
    if not cwd:
        return "(unknown)"
    norm = cwd.replace("\\", "/").rstrip("/")
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return "(unknown)"
    if "worktrees" in parts:
        idx = parts.index("worktrees")
        if idx + 1 < len(parts):
            base = parts[max(0, idx - 2)] if idx >= 2 else parts[0]
            return f"{base} (wt: {parts[idx + 1]})"
    return parts[-1]


def categorize_tool(name: str) -> tuple[str, str]:
    """Return (category, subcategory). category in: builtin, subagent, mcp, plugin, unknown."""
    if not name:
        return "unknown", ""
    if name == "Agent":
        return "subagent", "Agent"
    if name.startswith("mcp__"):
        rest = name[len("mcp__"):]
        server, _, _ = rest.partition("__")
        # detect plugin-namespaced MCP (has 'plugin' prefix in server name)
        if server.startswith("plugin_"):
            return "plugin", server
        return "mcp", server
    if name.startswith("plugin_"):
        return "plugin", name.split("_")[1] if "_" in name else name
    builtin_set = {
        "Bash", "Edit", "Grep", "Glob", "Read", "Write", "MultiEdit", "NotebookEdit",
        "WebFetch", "WebSearch", "TodoWrite", "Task", "ToolSearch", "PowerShell",
        "ExitPlanMode", "EnterPlanMode", "AskUserQuestion", "Monitor", "TaskOutput",
        "TaskStop", "ScheduleWakeup", "Skill", "PushNotification", "RemoteTrigger",
    }
    if name in builtin_set:
        return "builtin", name
    # Built-in CLI tools that share a verb prefix with their MCP equivalents
    # (e.g. "ReadMcpResourceTool" looks like "Read..."). Match an explicit
    # closed list rather than a broad startswith — prevents misclassifying
    # MCP tools whose names happen to begin with "Read", "List", etc.
    builtin_prefixed = {
        "CronCreate", "CronDelete", "CronList",
        "ListMcpResourcesTool", "ReadMcpResourceTool",
        "NotebookEdit",
    }
    if name in builtin_prefixed:
        return "builtin", name
    return "unknown", name


def process() -> dict:
    files = discover_jsonl_files()
    if not files:
        print("No JSONL files found.", file=sys.stderr)
        return {}

    print(f"Found {len(files)} JSONL files ({sum(1 for _, s in files if s == 'cli')} CLI, "
          f"{sum(1 for _, s in files if s == 'cowork')} cowork)", file=sys.stderr)

    # Per-project aggregates
    projects: dict[str, dict] = defaultdict(lambda: {
        "cwd": "", "name": "",
        "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
        "cost": 0.0, "cliCost": 0.0, "coworkCost": 0.0,
        "turns": 0, "models": defaultdict(int), "topToolCounts": defaultdict(int),
        "earliest": None, "latest": None,
    })

    # Per-tool aggregates
    tools: dict[str, dict] = defaultdict(lambda: {
        "name": "", "category": "", "subcategory": "",
        "invocations": 0, "turns": 0, "approxCost": 0.0,
        "approxTokens": 0, "projects": defaultdict(int),
    })

    # Per-source totals
    by_source = {
        "cli":    {"input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0, "cost": 0.0, "turns": 0},
        "cowork": {"input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0, "cost": 0.0, "turns": 0},
    }

    # Per-model totals
    by_model: dict[str, dict] = defaultdict(lambda: {
        "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0, "cost": 0.0, "turns": 0,
    })

    # MCP server aggregates
    mcp_servers: dict[str, dict] = defaultdict(lambda: {
        "server": "", "invocations": 0, "approxCost": 0.0, "tools": defaultdict(int),
    })

    # Subagent aggregates
    subagents: dict[str, dict] = defaultdict(lambda: {
        "type": "", "invocations": 0, "approxCost": 0.0,
    })

    grand_totals = {"input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0, "cost": 0.0, "turns": 0}

    # Daily trend buckets: keep both cost-only dims (for stacked charts) and richer
    # per-day-per-project/per-source/per-model data so client-side filters can
    # reconstruct token totals + cache hit ratios.
    def _ddict_richbucket():
        return {"cost": 0.0, "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0, "turns": 0}

    daily_trends: dict[str, dict] = defaultdict(lambda: {
        "cost": 0.0, "turns": 0, "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
        "byProject":   defaultdict(float),
        "byTool":      defaultdict(float),
        "byMCPServer": defaultdict(float),
        "byModel":     defaultdict(float),
        "byCategory":  defaultdict(float),
        "bySource":    defaultdict(float),
        # Rich per-dimension data (objects with cost + tokens)
        "projectsDetail": defaultdict(_ddict_richbucket),
        "sourceDetail":   defaultdict(_ddict_richbucket),
        "modelDetail":    defaultdict(_ddict_richbucket),
    })

    # Per-conversation (session) aggregates
    conversations: dict[str, dict] = defaultdict(lambda: {
        "sessionId": "", "source": "", "cwd": "", "name": "",
        "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
        "cost": 0.0, "turns": 0,
        "models": defaultdict(int), "tools": defaultdict(int),
        "earliest": None, "latest": None,
    })

    # Hourly buckets (timestamp granularity): "YYYY-MM-DDTHH" -> {cost, turns, byProject, byModel}
    hourly: dict[str, dict] = defaultdict(lambda: {
        "cost": 0.0, "turns": 0, "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
        "byProject": defaultdict(float), "byModel": defaultdict(float), "bySource": defaultdict(float),
    })

    # Day-of-week × hour heatmap: cost summed across all dates
    # weekday: 0=Mon ... 6=Sun, hour: 0..23
    heatmap_cost  = [[0.0 for _ in range(24)] for _ in range(7)]
    heatmap_turns = [[0    for _ in range(24)] for _ in range(7)]

    # Per-turn log (capped) — for the activity feed
    turn_log: list[dict] = []
    # Cap is configurable via env so heavy users can keep more in the
    # activity feed. Default 1000 keeps insights.json under ~1MB on
    # average for typical workloads.
    try:
        TURN_LOG_CAP = max(0, int(os.environ.get("CCUSAGE_TURN_LOG_CAP", "1000")))
    except ValueError:
        TURN_LOG_CAP = 1000

    parse_errors = 0

    for path, source in files:
        try:
            # Workaround for Windows MAX_PATH (260 chars) on deep cowork dirs
            open_path = str(path)
            if os.name == "nt" and len(open_path) > 240 and not open_path.startswith("\\\\?\\"):
                open_path = "\\\\?\\" + os.path.abspath(open_path)
            with open(open_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") != "assistant":
                        continue

                    msg = rec.get("message") or {}
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage") or {}
                    model = msg.get("model", "unknown")
                    cwd = rec.get("cwd", "")
                    ts = rec.get("timestamp", "")

                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    cw  = usage.get("cache_creation_input_tokens", 0)
                    cr  = usage.get("cache_read_input_tokens", 0)
                    cost = cost_for(model, usage)

                    # Skip empty turns (cache-only or system messages with no usage)
                    if inp == 0 and out == 0 and cw == 0 and cr == 0:
                        continue

                    # Grand totals
                    grand_totals["input"] += inp; grand_totals["output"] += out
                    grand_totals["cacheCreate"] += cw; grand_totals["cacheRead"] += cr
                    grand_totals["cost"] += cost; grand_totals["turns"] += 1

                    # Daily bucket — derive YYYY-MM-DD from timestamp
                    day_key = ts[:10] if ts else "unknown"
                    dt = daily_trends[day_key]
                    dt["cost"] += cost; dt["turns"] += 1
                    dt["input"] += inp; dt["output"] += out
                    dt["cacheCreate"] += cw; dt["cacheRead"] += cr
                    dt["byModel"][model] += cost
                    dt["bySource"][source] += cost
                    # Rich detail
                    md = dt["modelDetail"][model]
                    md["cost"] += cost; md["turns"] += 1
                    md["input"] += inp; md["output"] += out
                    md["cacheCreate"] += cw; md["cacheRead"] += cr
                    sd = dt["sourceDetail"][source]
                    sd["cost"] += cost; sd["turns"] += 1
                    sd["input"] += inp; sd["output"] += out
                    sd["cacheCreate"] += cw; sd["cacheRead"] += cr

                    # Hourly + heatmap
                    if ts and len(ts) >= 13:
                        hour_key = ts[:13]  # "YYYY-MM-DDTHH"
                        hb = hourly[hour_key]
                        hb["cost"] += cost; hb["turns"] += 1
                        hb["input"] += inp; hb["output"] += out
                        hb["cacheCreate"] += cw; hb["cacheRead"] += cr
                        hb["byProject"][project_name_from_cwd(cwd)] += cost
                        hb["byModel"][model] += cost
                        hb["bySource"][source] += cost
                        try:
                            from datetime import datetime as _dt
                            t = _dt.fromisoformat(ts.replace("Z", "+00:00"))
                            wd = t.weekday()  # 0=Mon
                            hr = t.hour
                            heatmap_cost[wd][hr] += cost
                            heatmap_turns[wd][hr] += 1
                        except Exception:
                            pass

                    # Per-conversation accumulator
                    sid = rec.get("sessionId", "(unknown)")
                    cv = conversations[sid]
                    cv["sessionId"] = sid
                    cv["source"]    = source
                    cv["cwd"]       = cwd
                    cv["name"]      = project_name_from_cwd(cwd)
                    cv["input"]    += inp; cv["output"] += out
                    cv["cacheCreate"] += cw; cv["cacheRead"] += cr
                    cv["cost"]     += cost; cv["turns"] += 1
                    cv["models"][model] += 1
                    if ts:
                        if cv["earliest"] is None or ts < cv["earliest"]: cv["earliest"] = ts
                        if cv["latest"]   is None or ts > cv["latest"]:   cv["latest"]   = ts

                    # By source
                    s = by_source[source]
                    s["input"] += inp; s["output"] += out
                    s["cacheCreate"] += cw; s["cacheRead"] += cr
                    s["cost"] += cost; s["turns"] += 1

                    # By model
                    m = by_model[model]
                    m["input"] += inp; m["output"] += out
                    m["cacheCreate"] += cw; m["cacheRead"] += cr
                    m["cost"] += cost; m["turns"] += 1

                    # By project (cwd)
                    proj_key = cwd or "(unknown)"
                    pr = projects[proj_key]
                    pr["cwd"] = cwd
                    pr["name"] = project_name_from_cwd(cwd)
                    pr["input"] += inp; pr["output"] += out
                    pr["cacheCreate"] += cw; pr["cacheRead"] += cr
                    pr["cost"] += cost; pr["turns"] += 1
                    pr["models"][model] += 1
                    if source == "cli":
                        pr["cliCost"] += cost
                    else:
                        pr["coworkCost"] += cost
                    # Daily attribution by project name + rich detail
                    pname = pr["name"]
                    daily_trends[day_key]["byProject"][pname] += cost
                    pd = daily_trends[day_key]["projectsDetail"][pname]
                    pd["cost"] += cost; pd["turns"] += 1
                    pd["input"] += inp; pd["output"] += out
                    pd["cacheCreate"] += cw; pd["cacheRead"] += cr
                    if source == "cli":
                        pd["cliCost"] = pd.get("cliCost", 0) + cost
                    else:
                        pd["coworkCost"] = pd.get("coworkCost", 0) + cost
                    if ts:
                        if pr["earliest"] is None or ts < pr["earliest"]: pr["earliest"] = ts
                        if pr["latest"]   is None or ts > pr["latest"]:   pr["latest"]   = ts

                    # Tools used in this turn
                    content = msg.get("content")
                    tool_blocks = []
                    if isinstance(content, list):
                        tool_blocks = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
                    tool_names_in_turn = [(tb.get("name") or "") for tb in tool_blocks]

                    # Per-turn log entry (no message content, just metadata)
                    if ts:
                        turn_log.append({
                            "timestamp": ts,
                            "sessionId": sid,
                            "source":    source,
                            "model":     model,
                            "cwd":       cwd,
                            "project":   project_name_from_cwd(cwd),
                            "cost":      round(cost, 6),
                            "input":     inp, "output": out,
                            "cacheCreate": cw, "cacheRead": cr,
                            "tools":     tool_names_in_turn[:8],  # cap to first 8 names
                            "toolCount": len(tool_blocks),
                        })

                    n_tools = len(tool_blocks)
                    if n_tools == 0:
                        continue
                    # Attribute turn cost evenly across tools used
                    cost_share = cost / n_tools
                    token_share = (inp + out + cw + cr) / n_tools

                    for tb in tool_blocks:
                        tname = tb.get("name", "")
                        cat, sub = categorize_tool(tname)

                        t = tools[tname]
                        t["name"] = tname
                        t["category"] = cat
                        t["subcategory"] = sub
                        t["invocations"] += 1
                        t["approxCost"] += cost_share
                        t["approxTokens"] += token_share
                        t["projects"][proj_key] += 1
                        pr["topToolCounts"][tname] += 1

                        # Daily attribution
                        daily_trends[day_key]["byTool"][tname] += cost_share
                        daily_trends[day_key]["byCategory"][cat] += cost_share

                        if cat == "mcp":
                            ms = mcp_servers[sub]
                            ms["server"] = sub
                            ms["invocations"] += 1
                            ms["approxCost"] += cost_share
                            tool_short = tname[len(f"mcp__{sub}__"):] if tname.startswith(f"mcp__{sub}__") else tname
                            ms["tools"][tool_short] += 1
                            daily_trends[day_key]["byMCPServer"][sub] += cost_share

                        if cat == "subagent":
                            stype = (tb.get("input") or {}).get("subagent_type", "default")
                            sa = subagents[stype]
                            sa["type"] = stype
                            sa["invocations"] += 1
                            sa["approxCost"] += cost_share

        except (OSError, UnicodeDecodeError) as e:
            parse_errors += 1
            print(f"  warn: {path}: {e}", file=sys.stderr)

    # Per-model no-cache hypothetical
    for model_name, m in by_model.items():
        fam = model_family(model_name)
        r = RATES[fam]
        # Without caching: cache_read would have been input tokens at full input rate
        # cache_create cost would not exist (no cache writes either)
        # Approximate "saved" = (cache_read * 9/10 of input rate) - (cache_create extra of 0.25x)
        no_cache_cost = (
            (m["input"] + m["cacheRead"] + m["cacheCreate"]) * r["input"] / 1e6
            + m["output"] * r["output"] / 1e6
        )
        m["noCacheCost"] = round(no_cache_cost, 4)
        m["cacheSaved"] = round(no_cache_cost - m["cost"], 4)
        m["cacheSavedPct"] = round((no_cache_cost - m["cost"]) / no_cache_cost * 100, 1) if no_cache_cost > 0 else 0

    # Sort and serialize
    def to_list(d, key="cost"):
        items = []
        for k, v in d.items():
            v = dict(v)
            for kk, vv in list(v.items()):
                if isinstance(vv, defaultdict):
                    v[kk] = dict(vv)
            items.append(v)
        return sorted(items, key=lambda x: x.get(key, 0), reverse=True)

    project_list = []
    for v in projects.values():
        v = dict(v)
        v["models"] = dict(v["models"])
        # top tools (limit 8)
        top_tools = sorted(v["topToolCounts"].items(), key=lambda x: x[1], reverse=True)[:8]
        v["topTools"] = [{"name": n, "count": c} for n, c in top_tools]
        del v["topToolCounts"]
        v["cacheHitRatio"] = round(v["cacheRead"] / (v["cacheRead"] + v["cacheCreate"]), 4) if (v["cacheRead"] + v["cacheCreate"]) > 0 else 0
        project_list.append(v)
    project_list.sort(key=lambda x: x["cost"], reverse=True)

    tool_list = []
    for v in tools.values():
        v = dict(v)
        v["projects"] = dict(v["projects"])
        v["approxCost"] = round(v["approxCost"], 4)
        v["approxTokens"] = int(v["approxTokens"])
        tool_list.append(v)
    tool_list.sort(key=lambda x: x["approxCost"], reverse=True)

    mcp_list = []
    for v in mcp_servers.values():
        v = dict(v)
        v["tools"] = dict(v["tools"])
        v["approxCost"] = round(v["approxCost"], 4)
        v["topTools"] = sorted(v["tools"].items(), key=lambda x: x[1], reverse=True)[:5]
        mcp_list.append(v)
    mcp_list.sort(key=lambda x: x["approxCost"], reverse=True)

    subagent_list = sorted(
        [{"type": v["type"], "invocations": v["invocations"], "approxCost": round(v["approxCost"], 4)}
         for v in subagents.values()],
        key=lambda x: x["approxCost"], reverse=True,
    )

    # Compose daily trend output — emit FULL per-day buckets (no top-N truncation)
    # so client-side date filters can re-aggregate without information loss.
    # The HTML page applies top-N at chart render time for legend cleanliness.
    def _round_bucket(b: dict) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in b.items()}

    daily_trend_list = []
    unknown_day_turns = 0
    unknown_day_cost  = 0.0
    for day in sorted(daily_trends.keys()):
        if day == "unknown":
            unknown_day_turns = daily_trends[day].get("turns", 0)
            unknown_day_cost  = daily_trends[day].get("cost",  0.0)
            continue
        b = daily_trends[day]
        daily_trend_list.append({
            "date":         day,
            "cost":         round(b["cost"], 4),
            "turns":        b["turns"],
            "input":        b["input"],
            "output":       b["output"],
            "cacheCreate":  b["cacheCreate"],
            "cacheRead":    b["cacheRead"],
            "byProject":    {k: round(v, 4) for k, v in b["byProject"].items()},
            "byCategory":   {k: round(v, 4) for k, v in b["byCategory"].items()},
            "bySource":     {k: round(v, 4) for k, v in b["bySource"].items()},
            "byModel":      {k: round(v, 4) for k, v in b["byModel"].items()},
            "byMCPServer":  {k: round(v, 4) for k, v in b["byMCPServer"].items()},
            "byTool":       {k: round(v, 4) for k, v in b["byTool"].items()},
            "projectsDetail": {k: _round_bucket(dict(v)) for k, v in b["projectsDetail"].items()},
            "sourceDetail":   {k: _round_bucket(dict(v)) for k, v in b["sourceDetail"].items()},
            "modelDetail":    {k: _round_bucket(dict(v)) for k, v in b["modelDetail"].items()},
        })

    # Conversations list
    conversation_list = []
    for cv in conversations.values():
        cv = dict(cv)
        cv["models"] = dict(cv["models"])
        # Compute derived fields
        denom = cv["cacheRead"] + cv["cacheCreate"]
        cv["cacheHitRatio"] = round(cv["cacheRead"] / denom, 4) if denom > 0 else 0
        cv["totalTokens"] = cv["input"] + cv["output"] + cv["cacheCreate"] + cv["cacheRead"]
        # Avg context size approximation: tokens per turn (input + cache_read on assistant turns)
        cv["avgContextPerTurn"] = round((cv["input"] + cv["cacheRead"]) / cv["turns"], 0) if cv["turns"] > 0 else 0
        # Duration in minutes (between first and last assistant message)
        if cv["earliest"] and cv["latest"] and cv["earliest"] != cv["latest"]:
            try:
                from datetime import datetime as _dt
                t1 = _dt.fromisoformat(cv["earliest"].replace("Z", "+00:00"))
                t2 = _dt.fromisoformat(cv["latest"].replace("Z", "+00:00"))
                cv["durationMinutes"] = round((t2 - t1).total_seconds() / 60, 1)
            except Exception:
                cv["durationMinutes"] = 0
        else:
            cv["durationMinutes"] = 0
        cv["cost"] = round(cv["cost"], 4)
        conversation_list.append(cv)
    conversation_list.sort(key=lambda x: x["cost"], reverse=True)

    # Hourly trend list — sorted by hour key
    hourly_list = []
    for hour_key in sorted(hourly.keys()):
        b = hourly[hour_key]
        hourly_list.append({
            "hour":         hour_key,
            "cost":         round(b["cost"], 4),
            "turns":        b["turns"],
            "input":        b["input"], "output": b["output"],
            "cacheCreate":  b["cacheCreate"], "cacheRead": b["cacheRead"],
            "byProject":    {k: round(v, 4) for k, v in b["byProject"].items()},
            "byModel":      {k: round(v, 4) for k, v in b["byModel"].items()},
            "bySource":     {k: round(v, 4) for k, v in b["bySource"].items()},
        })

    # Cap turn log to most recent N (sorted descending by timestamp).
    # The cap is configurable via the env var CCUSAGE_TURN_LOG_CAP for users
    # with very heavy histories who need more in the timeline activity feed.
    turn_log.sort(key=lambda t: t["timestamp"], reverse=True)
    turn_log_capped = turn_log[:TURN_LOG_CAP]

    output = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "filesScanned": len(files),
        "parseErrors": parse_errors,
        # Turns whose timestamp couldn't be parsed are bucketed into a synthetic
        # "unknown" day key. We drop them from dailyTrend (the chart can't
        # plot them) but expose the count and aggregate cost here so KPIs and
        # daily-trend totals don't silently disagree.
        "unknownDay": {
            "turns": unknown_day_turns,
            "cost":  round(unknown_day_cost, 4),
        },
        "conversations": conversation_list,
        "dailyTrend":  daily_trend_list,
        "hourlyTrend": hourly_list,
        "heatmap":     {
            "weekdayLabels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "cost":  [[round(v, 4) for v in row] for row in heatmap_cost],
            "turns": heatmap_turns,
        },
        "turnLog":     turn_log_capped,
        "turnLogTotal": len(turn_log),
        "totals": {**grand_totals, "cost": round(grand_totals["cost"], 4)},
        "bySource": {
            k: {**v, "cost": round(v["cost"], 4)} for k, v in by_source.items()
        },
        "byModel": [
            {"model": k, **{kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}}
            for k, v in sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True)
        ],
        "byProject": project_list,
        "byTool": tool_list,
        "byMCPServer": mcp_list,
        "bySubagent": subagent_list,
    }

    return output


if __name__ == "__main__":
    out = process()
    script_dir = Path(__file__).resolve().parent
    out_path = script_dir / "insights.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    # Also write a JS shim so the dashboard works via file:// (no fetch needed)
    js_path = script_dir / "insights_data.js"
    js_path.write_text(
        "window.INSIGHTS = " + json.dumps(out, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"\nWrote {out_path}")
    print(f"  Total cost (API equivalent): ${out['totals']['cost']:.2f}")
    print(f"  Turns: {out['totals']['turns']}")
    print(f"  Projects: {len(out['byProject'])}")
    print(f"  Tools tracked: {len(out['byTool'])}")
    print(f"  MCP servers:   {len(out['byMCPServer'])}")
    print(f"  Subagent types: {len(out['bySubagent'])}")
