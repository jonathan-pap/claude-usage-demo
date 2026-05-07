#!/usr/bin/env python3
"""
generate_demo_data.py — Creates synthetic but realistic demo data for the claude-usage dashboard.

Run from the repo root:
    python generate_demo_data.py

Produces:
    usage_data.js           window.USAGE_DATA  (Charts tab)
    insights_data.js        window.INSIGHTS    (Breakdown tab)
    machines/               per-machine snapshots + manifest
"""

import json, math, os, random
from datetime import datetime, timedelta, timezone

random.seed(42)

# ─── Config ────────────────────────────────────────────────────────────────────

START  = datetime(2025,  7,  1, tzinfo=timezone.utc)
END    = datetime(2026,  4, 30, tzinfo=timezone.utc)
NOW    = datetime(2026,  5,  7, 12, 0, 0, tzinfo=timezone.utc)

TARGET_TOTAL = 2_050.0   # USD over the full period (~10 months)
MIN_DAY_COST = 1.50      # skip days below this (very quiet weekends)

DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]

PROJECTS = [
    {"name": "web-dashboard",  "path": "/home/alex/projects/web-dashboard",  "w": 0.26, "cli": 0.90, "model": "opus"},
    {"name": "api-service",    "path": "/home/alex/projects/api-service",    "w": 0.21, "cli": 0.85, "model": "sonnet"},
    {"name": "data-pipeline",  "path": "/home/alex/projects/data-pipeline",  "w": 0.17, "cli": 1.00, "model": "opus"},
    {"name": "ml-experiments", "path": "/home/alex/projects/ml-experiments", "w": 0.12, "cli": 1.00, "model": "opus"},
    {"name": "mobile-app",     "path": "/home/alex/projects/mobile-app",     "w": 0.10, "cli": 0.50, "model": "sonnet"},
    {"name": "docs-site",      "path": "/home/alex/projects/docs-site",      "w": 0.05, "cli": 0.40, "model": "haiku"},
    {"name": "infra-scripts",  "path": "/home/alex/projects/infra-scripts",  "w": 0.04, "cli": 1.00, "model": "sonnet"},
    {"name": "claude-usage",   "path": "/home/alex/projects/claude-usage",   "w": 0.03, "cli": 1.00, "model": "sonnet"},
    {"name": "game-prototype", "path": "/home/alex/projects/game-prototype", "w": 0.02, "cli": 0.80, "model": "haiku"},
]

RATES = {
    "claude-opus-4-7":           {"input": 7.50,  "output": 37.50, "cw": 9.375, "cr": 0.750},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00, "cw": 3.750, "cr": 0.300},
    "claude-haiku-4-5-20251001": {"input": 1.00,  "output":  5.00, "cw": 1.250, "cr": 0.100},
}

MODEL_WEIGHTS = {
    "opus":   {"claude-opus-4-7": 0.78, "claude-sonnet-4-6": 0.18, "claude-haiku-4-5-20251001": 0.04},
    "sonnet": {"claude-opus-4-7": 0.18, "claude-sonnet-4-6": 0.74, "claude-haiku-4-5-20251001": 0.08},
    "haiku":  {"claude-opus-4-7": 0.04, "claude-sonnet-4-6": 0.16, "claude-haiku-4-5-20251001": 0.80},
}

TOOLS = [
    # (name, category, subcategory, daily_inv_mean, cost_per_inv_usd)
    ("Bash",       "builtin", "Bash",      18.0, 0.052),
    ("Read",       "builtin", "Read",      32.0, 0.011),
    ("Edit",       "builtin", "Edit",      14.0, 0.019),
    ("Write",      "builtin", "Write",      5.0, 0.023),
    ("Glob",       "builtin", "Glob",       9.0, 0.007),
    ("Grep",       "builtin", "Grep",       7.5, 0.007),
    ("Agent",      "subagent","Agent",      1.4, 0.200),
    ("WebSearch",  "builtin", "WebSearch",  2.5, 0.031),
    ("WebFetch",   "builtin", "WebFetch",   1.8, 0.025),
    ("TodoWrite",  "builtin", "TodoWrite",  1.2, 0.006),
    ("Skill",      "builtin", "Skill",      0.9, 0.009),
    ("mcp__github-mcp__create_pull_request",  "mcp", "github-mcp",       0.35, 0.115),
    ("mcp__github-mcp__list_issues",          "mcp", "github-mcp",       1.10, 0.041),
    ("mcp__github-mcp__create_issue",         "mcp", "github-mcp",       0.40, 0.077),
    ("mcp__github-mcp__get_file_contents",    "mcp", "github-mcp",       1.50, 0.036),
    ("mcp__github-mcp__search_repositories",  "mcp", "github-mcp",       0.50, 0.046),
    ("mcp__filesystem-local__read_file",      "mcp", "filesystem-local", 2.00, 0.019),
    ("mcp__filesystem-local__write_file",     "mcp", "filesystem-local", 0.80, 0.023),
    ("mcp__filesystem-local__list_directory", "mcp", "filesystem-local", 1.20, 0.013),
    ("mcp__browser-tools__navigate",          "mcp", "browser-tools",    0.90, 0.057),
    ("mcp__browser-tools__screenshot",        "mcp", "browser-tools",    0.60, 0.064),
    ("mcp__browser-tools__get_page_text",     "mcp", "browser-tools",    0.70, 0.049),
    ("mcp__plugin_design_figma__get_design_context", "plugin", "design_figma",   0.50, 0.081),
    ("mcp__plugin_design_figma__get_metadata",       "plugin", "design_figma",   0.40, 0.057),
    ("mcp__plugin_design_figma__get_screenshot",     "plugin", "design_figma",   0.30, 0.067),
    ("mcp__plugin_design_figma__get_libraries",      "plugin", "design_figma",   0.20, 0.042),
    ("mcp__plugin_design_linear__authenticate",      "plugin", "design_linear",  0.12, 0.029),
    ("mcp__plugin_design_linear__complete_authentication","plugin","design_linear",0.12,0.029),
]

MCP_SERVER_TOOLS = {
    "github-mcp":       ["create_pull_request","list_issues","create_issue","get_file_contents","search_repositories"],
    "filesystem-local": ["read_file","write_file","list_directory"],
    "browser-tools":    ["navigate","screenshot","get_page_text"],
}

SUBAGENTS = [
    ("general-purpose",    0.28, 0.58),
    ("python-expert",      0.20, 0.61),
    ("frontend-architect", 0.16, 0.63),
    ("backend-architect",  0.13, 0.65),
    ("refactoring-expert", 0.10, 0.55),
    ("quality-engineer",   0.08, 0.53),
    ("security-engineer",  0.05, 0.60),
]

MACHINES = [
    {"name": "demo-laptop",  "platform": "macos",   "ver": "14.5", "share": 0.75},
    {"name": "demo-desktop", "platform": "windows",  "ver": "11",   "share": 0.25},
]

# ─── Helpers ───────────────────────────────────────────────────────────────────

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def pick_model(bias):
    w = MODEL_WEIGHTS[bias]
    return random.choices(list(w.keys()), weights=list(w.values()))[0]

def tokens_for_cost(cost, model, cr):
    """Approximate token breakdown for a given cost + cache ratio."""
    r = RATES[model]
    cr_f  = cr
    cc_f  = 0.08
    out_f = 0.065
    in_f  = max(0.001, 1 - cr_f - cc_f - out_f)
    denom = in_f * r["input"] + out_f * r["output"] + cc_f * r["cw"] + cr_f * r["cr"]
    if denom < 0.001:
        denom = 0.001
    scale = cost * 1e6 / denom
    return {
        "input":       int(in_f  * scale),
        "output":      int(out_f * scale),
        "cacheCreate": int(cc_f  * scale),
        "cacheRead":   int(cr_f  * scale),
    }

def cache_ratio(t):
    """t ∈ [0,1]: ratio improves from ~0.78 to ~0.95 as the user gets better at prompting."""
    base = 0.780 + 0.170 * t
    return min(0.98, max(0.65, base + random.uniform(-0.03, 0.03)))

# ─── Step 1: controlled daily costs ───────────────────────────────────────────

TOTAL_DAYS = len(DAYS)

def day_weight(d):
    t = (d - START).days / (END - START).days
    ramp   = 0.55 + 0.90 * t          # 0.55 → 1.45 over period
    wf     = 1.0 if d.weekday() < 5 else 0.14
    noise  = 0.60 + 0.80 * random.random()  # 0.60–1.40
    return max(0.0, ramp * wf * noise)

raw_weights = [day_weight(d) for d in DAYS]
raw_costs   = [w / sum(raw_weights) * TARGET_TOTAL for w in raw_weights]

# Filter very quiet days, then rescale to preserve TARGET_TOTAL
active_pairs = [(d, c) for d, c in zip(DAYS, raw_costs) if c >= MIN_DAY_COST]
active_sum   = sum(c for _, c in active_pairs)
scale        = TARGET_TOTAL / active_sum
active_pairs = [(d, round(c * scale, 4)) for d, c in active_pairs]

# ─── Step 2: build daily_records (usage_data) ─────────────────────────────────

daily_records = []
for day, cost in active_pairs:
    t  = (day - START).days / (END - START).days
    cr = cache_ratio(t)

    cli_frac  = random.uniform(0.70, 0.95)
    cli_cost  = round(cost * cli_frac, 4)
    cow_cost  = round(cost - cli_cost, 4)

    n_models  = random.choices([1, 2, 3], weights=[0.35, 0.50, 0.15])[0]
    all_m     = list(RATES.keys())
    day_models= random.sample(all_m, k=min(n_models, len(all_m)))
    model_str = [m.replace("claude-", "").replace("-20251001", "") for m in day_models]

    toks = tokens_for_cost(cost, day_models[0], cr)

    daily_records.append({
        "date":                day.strftime("%Y-%m-%d"),
        "inputTokens":         toks["input"],
        "outputTokens":        toks["output"],
        "cacheCreationTokens": toks["cacheCreate"],
        "cacheReadTokens":     toks["cacheRead"],
        "totalTokens":         sum(toks.values()),
        "totalCost":           cost,
        "cliCost":             cli_cost,
        "coworkCost":          cow_cost,
        "models":              model_str,
        "cacheHitRatio":       round(cr, 4),
    })

# ─── Aggregate totals ─────────────────────────────────────────────────────────

def sum_key(records, key):
    return sum(r[key] for r in records)

total_input   = sum_key(daily_records, "inputTokens")
total_output  = sum_key(daily_records, "outputTokens")
total_cc      = sum_key(daily_records, "cacheCreationTokens")
total_cr      = sum_key(daily_records, "cacheReadTokens")
total_tokens  = sum_key(daily_records, "totalTokens")
total_cost    = round(sum_key(daily_records, "totalCost"), 4)
total_cli     = round(sum_key(daily_records, "cliCost"), 4)
total_cowork  = round(sum_key(daily_records, "coworkCost"), 4)
overall_cr    = round(total_cr / max(1, total_cr + total_cc), 4)

# ─── usage_data.js ─────────────────────────────────────────────────────────────

usage_data = {
    "schemaVersion": 1,
    "daily": daily_records,
    "snapshots": [
        {"collectedAt": fmt_dt(NOW - timedelta(days=90)),
         "totalCost": round(total_cost * 0.30, 4), "totalTokens": int(total_tokens * 0.30),
         "daysCovered": int(len(daily_records) * 0.33)},
        {"collectedAt": fmt_dt(NOW - timedelta(days=30)),
         "totalCost": round(total_cost * 0.72, 4), "totalTokens": int(total_tokens * 0.72),
         "daysCovered": int(len(daily_records) * 0.72)},
        {"collectedAt": fmt_dt(NOW),
         "totalCost": total_cost, "totalTokens": total_tokens,
         "daysCovered": len(daily_records)},
    ],
    "description": "Demo data — synthetic but realistic Claude Code usage across 6 months.",
    "totals": {
        "inputTokens": total_input, "outputTokens": total_output,
        "cacheCreationTokens": total_cc, "cacheReadTokens": total_cr,
        "totalTokens": total_tokens, "totalCost": total_cost,
        "cliCost": total_cli, "coworkCost": total_cowork,
        "cacheHitRatio": overall_cr,
    },
    "lastUpdated": daily_records[-1]["date"],
}

# ─── Insights: byProject ──────────────────────────────────────────────────────

by_project = []
for p in PROJECTS:
    share = p["w"]
    pcost = round(total_cost * share, 4)
    cr    = round(overall_cr * random.uniform(0.93, 1.07), 4)
    toks  = tokens_for_cost(pcost, pick_model(p["model"]), cr)
    turns = max(10, int(pcost / 0.055 * random.uniform(0.85, 1.15)))
    by_project.append({
        "cwd": p["path"], "name": p["name"], **toks,
        "cost": pcost,
        "cliCost": round(pcost * p["cli"], 4),
        "coworkCost": round(pcost * (1 - p["cli"]), 4),
        "turns": turns, "cacheHitRatio": cr,
        "models": {"claude-opus-4-7": int(turns * 0.4), "claude-sonnet-4-6": int(turns * 0.5)},
        "earliest": fmt_dt(START + timedelta(days=random.randint(0, 5))),
    })
by_project.sort(key=lambda x: -x["cost"])

# ─── Insights: byTool ─────────────────────────────────────────────────────────

n_days   = len(daily_records)
by_tool  = []
for name, cat, subcat, daily_mean, cpp in TOOLS:
    inv  = max(1, int(daily_mean * n_days * random.uniform(0.80, 1.20)))
    cost = round(inv * cpp * random.uniform(0.90, 1.10), 4)
    by_tool.append({
        "name": name, "category": cat, "subcategory": subcat,
        "invocations": inv, "turns": 0,
        "approxCost": cost, "approxTokens": int(cost * 1e6 / 3.0), "projects": {},
    })
by_tool.sort(key=lambda x: -x["approxCost"])

# ─── Insights: byMCPServer ────────────────────────────────────────────────────

by_mcp = []
for server, tools in MCP_SERVER_TOOLS.items():
    srv_tools = [t for t in TOOLS if t[2] == server]
    total_inv  = sum(max(1, int(t[3] * n_days * random.uniform(0.80, 1.20))) for t in srv_tools)
    total_cost_mcp = round(sum(max(1, int(t[3] * n_days * random.uniform(0.80, 1.20))) * t[4] for t in srv_tools), 4)
    tool_counts = {tool: max(1, int(n_days * random.uniform(0.3, 0.8))) for tool in tools}
    top_tools   = sorted(tool_counts.items(), key=lambda x: -x[1])
    by_mcp.append({
        "server": server, "invocations": total_inv, "approxCost": total_cost_mcp,
        "tools": tool_counts, "topTools": top_tools[:5],
    })
by_mcp.sort(key=lambda x: -x["approxCost"])

# ─── Insights: bySubagent ─────────────────────────────────────────────────────

agent_inv = next((t["invocations"] for t in by_tool if t["name"] == "Agent"), 100)
by_subagent = []
for s_type, weight, cpp in SUBAGENTS:
    inv  = max(1, int(agent_inv * weight * random.uniform(0.85, 1.15)))
    cost = round(inv * cpp * random.uniform(0.90, 1.10), 4)
    by_subagent.append({"type": s_type, "invocations": inv, "approxCost": cost})
by_subagent.sort(key=lambda x: -x["approxCost"])

# ─── Insights: byModel ────────────────────────────────────────────────────────

model_shares = {"claude-opus-4-7": 0.44, "claude-sonnet-4-6": 0.48, "claude-haiku-4-5-20251001": 0.08}
by_model = []
for model, share in model_shares.items():
    r = RATES[model]
    mcost = total_cost * share
    cr    = round(overall_cr * random.uniform(0.96, 1.04), 4)
    toks  = tokens_for_cost(mcost, model, cr)
    turns = max(10, int(mcost / 0.055 * random.uniform(0.90, 1.10)))
    no_cache = ((toks["input"] + toks["cacheRead"] + toks["cacheCreate"]) * r["input"] + toks["output"] * r["output"]) / 1e6
    saved    = no_cache - mcost
    by_model.append({
        "model": model, **toks, "cost": round(mcost, 4), "turns": turns,
        "noCacheCost": round(no_cache, 4), "cacheSaved": round(saved, 4),
        "cacheSavedPct": round(saved / max(0.001, no_cache) * 100, 1),
    })

# ─── Insights: bySource ───────────────────────────────────────────────────────

def scale_toks(frac):
    return {"input": int(total_input*frac), "output": int(total_output*frac),
            "cacheCreate": int(total_cc*frac), "cacheRead": int(total_cr*frac)}

cli_frac   = total_cli / max(0.001, total_cost)
cow_frac   = total_cowork / max(0.001, total_cost)
by_source  = {
    "cli":    {"cost": total_cli,    "turns": int(total_cost / 0.055 * cli_frac), **scale_toks(cli_frac)},
    "cowork": {"cost": total_cowork, "turns": int(total_cost / 0.055 * cow_frac), **scale_toks(cow_frac)},
}

# ─── Insights: dailyTrend ─────────────────────────────────────────────────────

daily_trend = []
for rec in daily_records:
    date = rec["date"]
    cost = rec["totalCost"]
    t    = (datetime.fromisoformat(date).replace(tzinfo=timezone.utc) - START).days / (END - START).days
    cr   = cache_ratio(t)
    toks = {"input": rec["inputTokens"], "output": rec["outputTokens"],
            "cacheCreate": rec["cacheCreationTokens"], "cacheRead": rec["cacheReadTokens"]}
    turns = max(1, int(cost / 0.055))

    # Distribute cost across projects
    proj_detail = {}
    remaining   = cost
    for i, p in enumerate(PROJECTS):
        if i == len(PROJECTS) - 1:
            pcost = round(remaining, 4)
        else:
            noise = 0.60 + 0.80 * random.random()
            pcost = round(cost * p["w"] * noise, 4)
            remaining -= pcost
        if pcost < 0.0001:
            continue
        cli_c  = round(pcost * p["cli"], 4)
        cow_c  = round(pcost - cli_c, 4)
        pt     = tokens_for_cost(pcost, pick_model(p["model"]), cr)
        proj_detail[p["name"]] = {
            "cost": pcost, "cliCost": cli_c, "coworkCost": cow_c,
            "turns": max(1, int(pcost / 0.055)), **pt,
        }

    cli_day = sum(v["cliCost"] for v in proj_detail.values())
    cow_day = sum(v["coworkCost"] for v in proj_detail.values())
    model_d = random.choices(list(model_shares.keys()), weights=list(model_shares.values()))[0]
    model_l = model_d.replace("claude-", "").replace("-20251001", "")

    daily_trend.append({
        "date": date, "cost": round(cost, 4), "turns": turns, **toks,
        "byProject":     {p: round(v["cost"], 4) for p, v in proj_detail.items()},
        "byCategory":    {"builtin": round(cost*0.60,4), "mcp": round(cost*0.22,4),
                          "plugin": round(cost*0.08,4), "subagent": round(cost*0.10,4)},
        "bySource":      {"cli": round(cli_day,4), "cowork": round(cow_day,4)},
        "byModel":       {model_l: round(cost, 4)},
        "byMCPServer":   {s["server"]: round(cost*0.22/max(1,len(by_mcp)),4) for s in by_mcp},
        "byTool":        {},
        "projectsDetail":proj_detail,
        "sourceDetail":  {
            "cli":    {"cost": round(cli_day,4), "turns": int(turns*cli_frac), **toks},
            "cowork": {"cost": round(cow_day,4), "turns": int(turns*cow_frac), **toks},
        },
        "modelDetail":   {model_d: {"cost": round(cost,4), "turns": turns, **toks}},
    })

# ─── Insights: hourlyTrend ────────────────────────────────────────────────────

HOUR_DIST = {9:0.14,10:0.16,11:0.12,12:0.06,13:0.05,14:0.14,15:0.13,16:0.10,17:0.07,18:0.03}
hourly_trend = []
for rec in daily_records:
    date = rec["date"]
    cost = rec["totalCost"]
    for h, frac in HOUR_DIST.items():
        hcost = round(cost * frac * random.uniform(0.5, 1.5), 4)
        if hcost < 0.01:
            continue
        hourly_trend.append({
            "hour":  f"{date}T{h:02d}",
            "cost":  hcost,
            "turns": max(1, int(hcost / 0.055)),
        })

# ─── Insights: heatmap ────────────────────────────────────────────────────────

hm_cost, hm_turns = {}, {}
for rec in daily_records:
    dt  = datetime.fromisoformat(rec["date"]).replace(tzinfo=timezone.utc)
    wd  = dt.weekday()
    wk  = dt.isocalendar()[1]
    key = f"{wk}-{wd}"
    hm_cost[key]  = round(hm_cost.get(key,  0) + rec["totalCost"], 4)
    hm_turns[key] = hm_turns.get(key, 0) + max(1, int(rec["totalCost"] / 0.055))

heatmap = {"weekdayLabels": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
           "cost": hm_cost, "turns": hm_turns}

# ─── Insights: conversations ──────────────────────────────────────────────────

conversations = []
sid = 1000
for p in PROJECTS:
    n_sess = max(2, int(len(daily_records) * p["w"] * 0.38))
    base_c = total_cost * p["w"] / n_sess
    for _ in range(n_sess):
        pcost = round(base_c * random.uniform(0.3, 2.5), 4)
        toks  = tokens_for_cost(pcost, pick_model(p["model"]), overall_cr)
        conversations.append({
            "sessionId": f"demo-{sid:04d}",
            "source":    "cli" if random.random() < p["cli"] else "cowork",
            "cwd":       p["path"],
            "name":      p["name"],
            "cost":      pcost,
            "turns":     max(3, int(pcost / 0.055)),
            **toks,
            "totalTokens": sum(toks.values()),
        })
        sid += 1
conversations.sort(key=lambda x: -x["cost"])

# ─── Insights: turnLog (sample of recent turns) ───────────────────────────────

turn_log = []
for rec in daily_records[-60:]:
    date = rec["date"]
    dt   = datetime.fromisoformat(date + "T10:00:00+00:00")
    for p in random.choices(PROJECTS, weights=[p["w"] for p in PROJECTS], k=min(12, int(rec["totalCost"]/0.055))):
        ts = dt + timedelta(minutes=random.randint(0, 480))
        turn_log.append({
            "timestamp": fmt_dt(ts),
            "sessionId": f"demo-{random.randint(1000,1500):04d}",
            "source":    "cli" if random.random() < p["cli"] else "cowork",
            "model":     pick_model(p["model"]),
            "cwd":       p["path"],
            "project":   p["name"],
            "cost":      round(rec["totalCost"] / max(1, int(rec["totalCost"]/0.055)), 6),
            "input":     450, "output": 820,
        })
        if len(turn_log) >= 1000:
            break
    if len(turn_log) >= 1000:
        break

# ─── Assemble INSIGHTS ────────────────────────────────────────────────────────

total_turns = sum(d["turns"] for d in daily_trend)

insights = {
    "generatedAt":   fmt_dt(NOW),
    "filesScanned":  int(total_turns * 1.25),
    "parseErrors":   0,
    "unknownDay":    {"turns": 0, "cost": 0},
    "conversations": conversations,
    "dailyTrend":    daily_trend,
    "hourlyTrend":   hourly_trend,
    "heatmap":       heatmap,
    "turnLog":       turn_log,
    "turnLogTotal":  total_turns,
    "totals":        {"input": total_input, "output": total_output,
                      "cacheCreate": total_cc, "cacheRead": total_cr,
                      "cost": total_cost, "turns": total_turns},
    "bySource":      by_source,
    "byModel":       by_model,
    "byProject":     by_project,
    "byTool":        by_tool,
    "byMCPServer":   by_mcp,
    "bySubagent":    by_subagent,
}

# ─── Machine snapshots ────────────────────────────────────────────────────────

os.makedirs("machines", exist_ok=True)
manifest_machines = []

for mach in MACHINES:
    mname = mach["name"]
    share = mach["share"]
    mcost = round(total_cost * share, 4)
    mtoks = int(total_tokens * share)

    m_daily = []
    for rec in daily_records:
        if random.random() < share * 1.15:
            m_daily.append({**rec,
                "totalCost":  round(rec["totalCost"]  * share, 4),
                "cliCost":    round(rec["cliCost"]    * share, 4),
                "coworkCost": round(rec["coworkCost"] * share, 4),
            })

    m_hourly = [{"hour": h["hour"], "cost": round(h["cost"]*share,4), "turns": int(h["turns"]*share)}
                for h in hourly_trend if random.random() < share * 1.1]

    snap = {
        "machine": mname, "platform": mach["platform"],
        "platformVersion": mach["ver"], "user": "alex",
        "lastUpdated": fmt_dt(NOW), "schemaVersion": 1,
        "dailyTotals": {
            "inputTokens": int(total_input*share), "outputTokens": int(total_output*share),
            "cacheCreationTokens": int(total_cc*share), "cacheReadTokens": int(total_cr*share),
            "totalTokens": mtoks, "totalCost": mcost,
            "cliCost": round(total_cli*share,4), "coworkCost": round(total_cowork*share,4),
            "cacheHitRatio": overall_cr,
        },
        "daily": m_daily,
        "snapshots": usage_data["snapshots"],
        "insights": {
            "totals":     {k: int(v*share) if isinstance(v,int) else round(v*share,4)
                           for k,v in insights["totals"].items()},
            "bySource":   by_source,
            "byModel":    by_model,
            "byProject":  [{**p, "cost": round(p["cost"]*share,4)} for p in by_project],
            "byTool":     [{**t, "approxCost": round(t["approxCost"]*share,4)} for t in by_tool],
            "byMCPServer":[{**m, "approxCost": round(m["approxCost"]*share,4)} for m in by_mcp],
            "bySubagent": [{**s, "approxCost": round(s["approxCost"]*share,4)} for s in by_subagent],
            "filesScanned": int(insights["filesScanned"]*share),
        },
        "hourlyTrend": m_hourly,
    }

    fname = f"machines/{mname}.json"
    with open(fname, "w") as f:
        json.dump(snap, f, separators=(",", ":"))
    print(f"  wrote {fname}  (${mcost:.2f}, {len(m_daily)} days)")

    manifest_machines.append({
        "machine": mname, "file": f"{mname}.json", "platform": mach["platform"],
        "lastUpdated": fmt_dt(NOW), "totalCost": mcost, "totalTokens": mtoks,
        "daysCovered": len(m_daily),
        "insightsCost": round(mcost * 2.8, 4), "insightsTurns": int(total_turns * share),
    })

manifest = {"schemaVersion": 1, "generatedAt": fmt_dt(NOW),
            "machineCount": len(MACHINES), "machines": manifest_machines}

with open("machines/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
with open("machines/manifest.js", "w") as f:
    f.write(f"window.MACHINES_MANIFEST = {json.dumps(manifest, separators=(',',':'))};")

all_machines = {m["name"]: {"platform": m["platform"], "lastUpdated": fmt_dt(NOW),
    "totals": {"inputTokens":int(total_input*m["share"]),"outputTokens":int(total_output*m["share"]),
               "cacheCreationTokens":int(total_cc*m["share"]),"cacheReadTokens":int(total_cr*m["share"]),
               "totalTokens":int(total_tokens*m["share"]),"totalCost":round(total_cost*m["share"],4),
               "cliCost":round(total_cli*m["share"],4),"coworkCost":round(total_cowork*m["share"],4),
               "cacheHitRatio":overall_cr}} for m in MACHINES}
with open("machines/all_machines.js", "w") as f:
    f.write(f"window.ALL_MACHINES = {json.dumps(all_machines, separators=(',',':'))};")

daily_merged = [{"date": r["date"], "cost": r["totalCost"],
                 "byMachine": {m["name"]: round(r["totalCost"]*m["share"],4) for m in MACHINES}}
                for r in daily_records]
with open("machines/daily_merged.js", "w") as f:
    f.write(f"window.DAILY_MERGED = {json.dumps(daily_merged, separators=(',',':'))};")

hourly_merged = [{"hour": h["hour"], "cost": h["cost"], "turns": h["turns"],
                  "byMachine": {m["name"]: round(h["cost"]*m["share"],4) for m in MACHINES}}
                 for h in hourly_trend]
with open("machines/hourly_merged.js", "w") as f:
    f.write(f"window.HOURLY_MERGED = {json.dumps(hourly_merged, separators=(',',':'))};")

print("  wrote machines/ manifest + merged files")

# ─── Write JS shims ────────────────────────────────────────────────────────────

with open("usage_data.js", "w") as f:
    f.write(f"window.USAGE_DATA = {json.dumps(usage_data, separators=(',',':'))};")
print(f"  wrote usage_data.js    {len(daily_records)} active days  ${total_cost:,.2f} total")

with open("insights_data.js", "w") as f:
    f.write(f"window.INSIGHTS = {json.dumps(insights, separators=(',',':'))};")
print(f"  wrote insights_data.js  {len(by_project)} projects  {len(by_tool)} tools  {len(by_subagent)} subagent types")

print(f"\nDone. Open index.html to view the demo dashboard.")
print(f"  Total cost: ${total_cost:,.2f}  Cache hit: {overall_cr*100:.1f}%  Turns: {total_turns:,}")
