#!/usr/bin/env bash
# Refresh usage_history.json with the latest merged CLI + cowork data, then
# rebuild per-machine snapshot, validate, and push to git.
#
# Robustness rules:
#  - Refuse to run if the working tree has uncommitted changes outside the
#    auto-generated files (so an in-progress code edit is never stashed).
#  - Pull from origin BEFORE generating snapshots so merged shims see every
#    machine's data and we never need --autostash.
#  - Validate every file in machines/ (JSON parses, no conflict markers)
#    before committing. Abort on any failure rather than push corruption.
#  - On push rejection, fetch and re-run (one retry) so a concurrent push
#    from another machine doesn't leave us stuck.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST=$(hostname | tr '[:upper:]' '[:lower:]')
# Make Python use the same hostname slug we use in commit messages so a
# single machine never scatters across multiple snapshot files.
export CCUSAGE_HOST="$HOST"

# ------------------------------------------------------------------
# Phase 0: git safety checks + pull (before any local changes)
# ------------------------------------------------------------------
git_safety_pull() {
  [ -d "$SCRIPT_DIR/.git" ] || return 0
  cd "$SCRIPT_DIR"

  # Reject if any uncommitted change exists outside of files we regenerate.
  # Anything else means the user has in-progress work we must not clobber.
  local dirty
  dirty=$(git status --porcelain -- \
    ':!machines/' \
    ':!usage_history.json' \
    ':!usage_data.js' \
    ':!insights.json' \
    ':!insights_data.js' 2>/dev/null || true)
  if [ -n "$dirty" ]; then
    echo "✗ Working tree has uncommitted changes outside generated files."
    echo "  Commit or stash these before running update_usage.sh:"
    echo "$dirty" | sed 's/^/    /'
    exit 1
  fi

  # A leftover stash from a prior failed run is a strong signal something's wrong.
  if git stash list 2>/dev/null | grep -q .; then
    echo "✗ Pre-existing stash entries detected. Resolve before running:"
    git stash list | sed 's/^/    /'
    echo "    (use 'git stash pop' or 'git stash drop')"
    exit 1
  fi

  echo "Pulling latest from origin..."
  # Discard any uncommitted churn in machines/ — we'll regenerate it. This
  # guarantees the rebase has nothing to stash and can fast-forward cleanly.
  git checkout -- machines/ 2>/dev/null || true

  # Do a plain --rebase. We DO NOT use -X theirs globally — that would
  # silently overwrite local code edits if a concurrent push touched
  # html/js/py/sh files. If a rebase conflict happens, we only
  # auto-resolve files INSIDE machines/ (we regenerate those moments
  # later anyway). Any conflict outside machines/ aborts.
  git fetch origin main 2>&1 | tail -3
  if ! git rebase origin/main 2>&1 | tail -5; then
    # Inspect conflicts: only auto-accept origin's side for machines/*.
    local code_conflict=0
    while IFS= read -r f; do
      if [ -z "$f" ]; then continue; fi
      case "$f" in
        machines/*)
          git checkout --theirs -- "$f"
          git add -- "$f"
          ;;
        *)
          code_conflict=1
          echo "✗ Rebase conflict in: $f"
          ;;
      esac
    done < <(git diff --name-only --diff-filter=U)

    if [ "$code_conflict" -eq 1 ]; then
      echo "✗ Conflicts in tracked code files. Aborting rebase."
      git rebase --abort 2>/dev/null || true
      exit 1
    fi
    # All remaining conflicts were in machines/ and have been resolved to
    # origin's version. Continue the rebase.
    if ! git -c core.editor=true rebase --continue 2>&1 | tail -5; then
      echo "✗ Rebase did not complete cleanly. Aborting."
      git rebase --abort 2>/dev/null || true
      exit 1
    fi
  fi

  # Belt-and-braces: scan tracked files for conflict markers in case origin
  # itself was poisoned by a previous bad push. We'll regenerate machines/
  # so this only matters for code files.
  if git grep -E '^(<{7} |={7}$|>{7} )' -- '*.html' '*.js' '*.py' '*.sh' 2>/dev/null; then
    echo "✗ Conflict markers in tracked files. Resolve before re-running."
    exit 1
  fi
}

git_safety_pull

# ------------------------------------------------------------------
# Phase 1: ccusage collection → usage_history.json + usage_data.js
# ------------------------------------------------------------------
OUT="$SCRIPT_DIR/usage_history.json"
TMP_CLI="$(mktemp)"
TMP_ALL="$(mktemp)"
TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_CLI" "$TMP_ALL" "$TMP_OUT"' EXIT

# Resolve cowork sessions root. $APPDATA may be empty when bash is launched
# from a parent process (PowerShell, scheduler) that didn't inherit it —
# fall back to the standard Windows location under $USERPROFILE.
#
# Bash glob patterns with backslashes don't work — backslash is the escape
# character, so "C:\Users\...\*\*\local_*\.claude" never matches anything.
# Whichever env var we use, normalize separators to forward slashes first.
# tr is the only reliable way to swap backslash for slash across bash
# versions — bash's parameter expansion ${var//\\/} is hit-or-miss for
# literal backslashes depending on quoting context.
_norm() { printf '%s' "$1" | tr '\\' '/'; }

if [ -n "${APPDATA:-}" ] && [ -d "$APPDATA" ]; then
  AGENT_ROOT="$(_norm "$APPDATA")/Claude/local-agent-mode-sessions"
elif [ -n "${USERPROFILE:-}" ] && [ -d "$USERPROFILE/AppData/Roaming" ]; then
  AGENT_ROOT="$(_norm "$USERPROFILE")/AppData/Roaming/Claude/local-agent-mode-sessions"
elif [ -n "${HOME:-}" ] && [ -d "$HOME/Library/Application Support/Claude" ]; then
  AGENT_ROOT="$HOME/Library/Application Support/Claude/local-agent-mode-sessions"
else
  AGENT_ROOT=""
fi
# Same treatment for CLI_DIR — used as a glob anchor and passed to ccusage.
CLI_DIR_NORM=""

CLI_DIR="$(_norm "${USERPROFILE:-$HOME}")/.claude"
ALL_DIRS="$CLI_DIR"
COWORK_COUNT=0

# If the PowerShell wrapper already discovered cowork dirs, prefer that
# list (PowerShell handles Windows paths and APPDATA reliably).
if [ -n "${CCUSAGE_COWORK_DIRS:-}" ]; then
  IFS=',' read -ra _COWORK_ARR <<< "$CCUSAGE_COWORK_DIRS"
  for d in "${_COWORK_ARR[@]}"; do
    [ -z "$d" ] && continue
    ALL_DIRS="$ALL_DIRS,$d"
    COWORK_COUNT=$((COWORK_COUNT + 1))
  done
elif [ -n "$AGENT_ROOT" ]; then
  while IFS= read -r d; do
    [ -z "$d" ] && continue
    ALL_DIRS="$ALL_DIRS,$d"
    COWORK_COUNT=$((COWORK_COUNT + 1))
  done < <(AGENT_ROOT="$AGENT_ROOT" python -c "
import os, sys
root = os.environ.get('AGENT_ROOT', '')
if not root:
    sys.exit(0)
if not os.path.isdir(root):
    sys.stderr.write(f'  [agent-discovery] AGENT_ROOT does not exist: {root}\n')
    sys.exit(0)
found = 0
for outer in os.listdir(root):
    p1 = os.path.join(root, outer)
    if not os.path.isdir(p1): continue
    for mid in os.listdir(p1):
        p2 = os.path.join(p1, mid)
        if not os.path.isdir(p2): continue
        for inner in os.listdir(p2):
            if not inner.startswith('local_'): continue
            cdir = os.path.join(p2, inner, '.claude')
            proj = os.path.join(cdir, 'projects')
            if os.path.isdir(proj):
                print(cdir.replace(os.sep, '/'))
                found += 1
if found == 0:
    sys.stderr.write(f'  [agent-discovery] No cowork sessions under {root}\n')
")
fi

# Detect a probable env-loss regression: previous run had cowork data but now
# we'd write zero. Warn loudly so the user notices before pushing zeros to git.
#
# IMPORTANT: Git Bash on Windows hands Python an MSYS-style path like
# /c/claude-usage/usage_history.json which Python can't open. To avoid that,
# we cd into SCRIPT_DIR and pass a relative path — works on every platform.
if [ -f "$SCRIPT_DIR/usage_history.json" ] && [ "$COWORK_COUNT" -eq 0 ]; then
  prev_cw=$(cd "$SCRIPT_DIR" && python -c "import json; print(json.load(open('usage_history.json',encoding='utf-8')).get('totals',{}).get('coworkCost',0))" 2>/dev/null)
  if [ -z "$prev_cw" ]; then prev_cw=0; fi
  if python -c "import sys; sys.exit(0 if float('$prev_cw') > 1.0 else 1)" 2>/dev/null; then
    echo "✗ Found 0 cowork dirs but previous run had \$$prev_cw of cowork cost."
    echo "  AGENT_ROOT='$AGENT_ROOT'"
    echo "  Likely \$APPDATA wasn't inherited from your shell."
    echo "  Aborting to avoid overwriting your data with zeros."
    exit 1
  fi
fi

echo "Scanning 1 CLI dir + $COWORK_COUNT cowork dirs..."
CLAUDE_CONFIG_DIR="$CLI_DIR"  npx -y ccusage@latest daily --json > "$TMP_CLI"
CLAUDE_CONFIG_DIR="$ALL_DIRS" npx -y ccusage@latest daily --json > "$TMP_ALL"

python - "$OUT" "$TMP_CLI" "$TMP_ALL" "$TMP_OUT" <<'PY'
import json, sys, datetime, os

out_path, cli_path, all_path, tmp_out = sys.argv[1:]

with open(cli_path, encoding="utf-8") as f: cli = json.load(f)
with open(all_path, encoding="utf-8") as f: alld = json.load(f)

# ccusage >= some recent version renamed "date" -> "period"; handle both
def _day(rec): return rec.get("period") or rec.get("date") or ""

cli_by_date = {_day(d): d["totalCost"] for d in cli["daily"]}

try:
    with open(out_path, encoding="utf-8") as f: hist = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    hist = {"schemaVersion": 1, "daily": [], "snapshots": []}

by_date = {d["date"]: d for d in hist.get("daily", [])}
for d in alld["daily"]:
    day = _day(d)
    if not day: continue
    cr, cc = d["cacheReadTokens"], d["cacheCreationTokens"]
    cli_cost = round(cli_by_date.get(day, 0), 4)
    total_cost = round(d["totalCost"], 4)
    by_date[day] = {
        "date": day,
        "inputTokens": d["inputTokens"],
        "outputTokens": d["outputTokens"],
        "cacheCreationTokens": cc,
        "cacheReadTokens": cr,
        "totalTokens": d["totalTokens"],
        "totalCost": total_cost,
        "cliCost": cli_cost,
        "coworkCost": round(total_cost - cli_cost, 4),
        "models": [m.replace("claude-", "").replace("-20251001", "") for m in d.get("modelsUsed", [])],
        "cacheHitRatio": round(cr / (cr + cc), 4) if (cr + cc) > 0 else 0,
    }

t = alld["totals"]
denom = t["cacheReadTokens"] + t["cacheCreationTokens"]
cli_total = round(cli["totals"]["totalCost"], 4)
all_total = round(t["totalCost"], 4)

hist["schemaVersion"] = 1
hist["description"] = "Merged Claude Code daily usage (CLI + cowork). Re-runs upsert by date and append a snapshot."
hist["daily"] = sorted(by_date.values(), key=lambda x: x["date"])
hist["totals"] = {
    "inputTokens": t["inputTokens"],
    "outputTokens": t["outputTokens"],
    "cacheCreationTokens": t["cacheCreationTokens"],
    "cacheReadTokens": t["cacheReadTokens"],
    "totalTokens": t["totalTokens"],
    "totalCost": all_total,
    "cliCost": cli_total,
    "coworkCost": round(all_total - cli_total, 4),
    "cacheHitRatio": round(t["cacheReadTokens"] / denom, 4) if denom > 0 else 0,
}
hist["lastUpdated"] = datetime.date.today().isoformat()
hist.setdefault("snapshots", []).append({
    "collectedAt": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "totalCost": all_total,
    "totalTokens": t["totalTokens"],
    "daysCovered": len(hist["daily"]),
})

with open(tmp_out, "w", encoding="utf-8") as f:
    json.dump(hist, f, indent=2, ensure_ascii=False)

print(f"  Days: {len(hist['daily'])}  Total: ${all_total:.2f} (CLI ${cli_total:.2f} + Cowork ${all_total - cli_total:.2f})  Hit ratio: {hist['totals']['cacheHitRatio']*100:.2f}%")
PY

mv "$TMP_OUT" "$OUT"
echo "Updated $OUT"

# JS shim for dashboard.html (needed for file:// browser access)
SCRIPT_DIR="$SCRIPT_DIR" OUT="$OUT" python -c "
import json, os
d = json.load(open(os.environ['OUT'], encoding='utf-8'))
open(os.path.join(os.environ['SCRIPT_DIR'], 'usage_data.js'), 'w', encoding='utf-8').write('window.USAGE_DATA = ' + json.dumps(d) + ';\n')
print('  Wrote usage_data.js')
"

# ------------------------------------------------------------------
# Phase 2: insights + machine snapshot
# ------------------------------------------------------------------
echo ""
echo "Building insights.json..."
PYTHONIOENCODING=utf-8 python "$SCRIPT_DIR/build_insights.py" 2>&1 | tail -8

echo ""
echo "Building machine snapshot..."
PYTHONIOENCODING=utf-8 python "$SCRIPT_DIR/build_machine_snapshot.py"

# ------------------------------------------------------------------
# Phase 3: validate generated files (fail fast — never push corruption)
# ------------------------------------------------------------------
echo ""
echo "Validating outputs..."
if ! PYTHONIOENCODING=utf-8 python "$SCRIPT_DIR/validate_machine_outputs.py"; then
  echo "✗ Validation failed. Local files left as-is, nothing pushed."
  exit 1
fi

# ------------------------------------------------------------------
# Phase 4: commit + push (with one race retry on non-fast-forward)
# ------------------------------------------------------------------
git_commit_and_push() {
  cd "$SCRIPT_DIR"
  git add machines/
  if git diff --cached --quiet; then
    echo "No machine changes to commit."
    return 0
  fi
  local msg="Update snapshot for ${HOST} ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  git commit -m "$msg" 2>&1 | tail -2

  # Retry up to 3 times with exponential backoff. Each retry rebases
  # onto fresh origin (auto-accepting machines/ from origin during
  # conflicts; ANY conflict outside machines/ aborts), regenerates
  # the merged shims, and re-commits before pushing again.
  local attempt
  for attempt in 1 2 3; do
    if git push origin main 2>&1 | tail -3; then
      return 0
    fi
    if [ "$attempt" -eq 3 ]; then
      echo "✗ Push rejected after 3 attempts. Manual resolution needed."
      return 1
    fi
    local sleep_s=$((attempt * 2))
    echo "  Push rejected (attempt ${attempt}/3) — rebasing and retrying in ${sleep_s}s..."
    sleep "$sleep_s"

    git reset --soft HEAD~1
    git checkout -- machines/
    git fetch origin main 2>&1 | tail -3
    if ! git rebase origin/main 2>&1 | tail -5; then
      local code_conflict=0
      while IFS= read -r f; do
        if [ -z "$f" ]; then continue; fi
        case "$f" in
          machines/*)
            git checkout --theirs -- "$f"
            git add -- "$f"
            ;;
          *)
            code_conflict=1
            echo "✗ Rebase conflict in: $f"
            ;;
        esac
      done < <(git diff --name-only --diff-filter=U)
      if [ "$code_conflict" -eq 1 ]; then
        echo "✗ Conflicts outside machines/. Aborting."
        git rebase --abort 2>/dev/null || true
        return 1
      fi
      if ! git -c core.editor=true rebase --continue 2>&1 | tail -5; then
        echo "✗ Rebase did not complete cleanly."
        git rebase --abort 2>/dev/null || true
        return 1
      fi
    fi
    PYTHONIOENCODING=utf-8 python "$SCRIPT_DIR/build_machine_snapshot.py"
    PYTHONIOENCODING=utf-8 python "$SCRIPT_DIR/validate_machine_outputs.py" || return 1
    git add machines/
    if git diff --cached --quiet; then
      echo "  After rebase, no new changes to push."
      return 0
    fi
    git commit -m "$msg"
  done
}

if [ -d "$SCRIPT_DIR/.git" ]; then
  echo ""
  REMOTE_URL=$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || echo "unknown")
  echo "Syncing to git ($REMOTE_URL)..."
  git_commit_and_push
fi
