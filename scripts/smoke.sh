#!/usr/bin/env bash
# Sangam smoke test: verifies every integration seam of the running stack.
# Usage: make smoke   (or: bash scripts/smoke.sh)
# Exits non-zero on the first failure with a clear message.

set -uo pipefail

BACKEND="${BACKEND_URL:-http://localhost:8010}"
FRONTEND="${FRONTEND_URL:-http://localhost:3000}"
AUTH=(-H "Authorization: Bearer dev")
PASS=0
FAIL=0

say()  { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); say "  ✗ $1"; }

check_status() { # name url expected [max-time]
  local name="$1" url="$2" want="$3" t="${4:-30}"
  local got
  got=$(curl -sL -o /dev/null -w "%{http_code}" --max-time "$t" "${AUTH[@]}" "$url")
  [[ "$got" == "$want" ]] && ok "$name ($got)" || bad "$name — expected $want, got $got ($url)"
}

check_contains() { # name url needle [max-time]
  local name="$1" url="$2" needle="$3" t="${4:-60}"
  if curl -s --max-time "$t" "${AUTH[@]}" "$url" | grep -q "$needle"; then
    ok "$name"
  else
    bad "$name — response from $url does not contain '$needle'"
  fi
}

check_json() { # name url python-assertion
  local name="$1" url="$2" expr="$3"
  if curl -s --max-time 30 "${AUTH[@]}" "$url" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert ($expr)
" 2>/dev/null; then
    ok "$name"
  else
    bad "$name — assertion '$expr' failed for $url"
  fi
}

say "── backend ──────────────────────────────────────"
check_status  "health endpoint"            "$BACKEND/health" 200 5
check_json    "stats: cohort counts"       "$BACKEND/api/meta/stats" "d['orgs'] == 10 and d['funders'] == 4"
check_json    "orgs: legacy array of 10"   "$BACKEND/api/orgs" "isinstance(d, list) and len(d) == 10"
check_json    "funders: latest_scores"     "$BACKEND/api/funders" "d[0]['latest_scores'].get('v1') is not None"
check_json    "scores: 8 assessments"      "$BACKEND/api/scores?limit=100" "d['total'] == 8"
check_json    "grants: 4 relationships"    "$BACKEND/api/grants" "d['total'] == 4"
check_json    "documents: 96 on file"      "$BACKEND/api/documents?limit=1" "d['total'] == 96"
check_status  "agent AG-UI health"         "$BACKEND/agent/health" 200 5

say "── frontend ─────────────────────────────────────"
check_status  "home redirects"             "$FRONTEND/" 200 60
check_contains "registry lists KABIL"      "$FRONTEND/registry" "KABIL" 90
check_contains "org profile renders"       "$FRONTEND/registry/kabil" "Registered December 2012" 90
check_contains "funder profile renders"    "$FRONTEND/registry/funders/axis-bank-foundation" "Axis Bank Foundation" 90
check_status  "unknown org 404s"           "$FRONTEND/registry/nonexistent-org" 404 60
check_status  "ask workspace"              "$FRONTEND/ask" 200 90
check_status  "resources"                  "$FRONTEND/resources" 200 60
check_status  "copilotkit runtime info"    "$FRONTEND/api/copilotkit/info" 200 30

say "── chat wire (runtime → backend → agent) ────────"
# A cheap end-to-end probe: run a real (tiny) agent turn through the runtime
# path the browser uses. Requires a model API key; counts as one LLM call.
if [[ "${SMOKE_SKIP_LLM:-0}" == "1" ]]; then
  say "  ‣ skipped (SMOKE_SKIP_LLM=1)"
else
  RESP=$(curl -sN --max-time 120 -X POST "$FRONTEND/api/copilotkit/agent/sangam_agent/run" \
    -H 'Content-Type: application/json' -H 'Accept: text/event-stream' \
    -d '{"threadId":"smoke-'"$(date +%s)"'","runId":"smoke-1","messages":[{"id":"m1","role":"user","content":"Reply with the single word: ok"}],"tools":[],"context":[],"state":{},"forwardedProps":{}}' | head -c 4000)
  if grep -q "RUN_STARTED" <<<"$RESP"; then
    ok "agent run streams through the runtime"
  else
    bad "agent run did not stream (no RUN_STARTED event)"
  fi
fi

say "─────────────────────────────────────────────────"
say "smoke: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
