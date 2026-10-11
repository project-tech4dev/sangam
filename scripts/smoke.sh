#!/usr/bin/env bash
# Sangam smoke test: verifies every integration seam of the running stack.
# Usage: make smoke   (or: bash scripts/smoke.sh)
# Exits non-zero on the first failure with a clear message.

set -uo pipefail
cd "$(dirname "$0")/.."  # the taxonomy check compares repo-relative paths

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

check_redirect() { # name url needle-in-Location — a signed-out request is sent to sign-in
  local name="$1" url="$2" needle="$3"
  local location
  location=$(curl -s -o /dev/null --max-time 60 -w "%{redirect_url}" "$url")
  [[ "$location" == *"$needle"* ]] && ok "$name" || bad "$name — redirect '$location' lacks '$needle'"
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
# >= not ==: Sangam Import adds funders and documents to whatever is seeded, so a
# fixed count would fail the first time someone runs an import. What matters here
# is that the seeded cohort is present, not that nothing was ever added to it.
check_json    "stats: cohort counts"       "$BACKEND/api/meta/stats" "d['orgs'] >= 10 and d['funders'] >= 4"
check_json    "orgs: legacy array of 10"   "$BACKEND/api/orgs" "isinstance(d, list) and len(d) == 10"
check_json    "funders: latest_scores"     "$BACKEND/api/funders" "d[0]['latest_scores'].get('v1') is not None"
check_json    "scores: 8 assessments"      "$BACKEND/api/scores?limit=100" "d['total'] == 8"
# >= since 0034: a grant is a partner line, and Import adds partner lines too.
check_json    "partner lines: 4+ grants"   "$BACKEND/api/partner-lines?org=kabil" "d['total'] >= 4"
check_json    "documents: 96+ on file"    "$BACKEND/api/documents?limit=1" "d['total'] >= 96"
check_status  "agent AG-UI health"         "$BACKEND/agent/health" 200 5

say "── frontend ─────────────────────────────────────"
# /resources/taxonomy and Import's tag vocabulary read copies of the seed files; seed/data/taxonomy is the source.
TAX_SRC="seed/data/taxonomy"
for TAX_COPY in frontend/features/taxonomy/data backend/app/ingest/data; do
  if diff -q "$TAX_SRC/themes.json" "$TAX_COPY/themes.json" >/dev/null && diff -q "$TAX_SRC/common.json" "$TAX_COPY/common.json" >/dev/null; then
    ok "taxonomy copies in $TAX_COPY match their seed files"
  else
    bad "taxonomy copies in $TAX_COPY differ from $TAX_SRC — see frontend/features/taxonomy/data/README.md"
  fi
done
check_contains "taxonomy shows the SHG theme" "$FRONTEND/resources/taxonomy" "Economic empowerment of SHGs" 90
check_status  "home page renders"          "$FRONTEND/" 200 60
check_contains "registry lists KABIL"      "$FRONTEND/registry" "KABIL" 90
check_contains "org profile renders"       "$FRONTEND/registry/kabil" "Registered December 2012" 90
check_contains "funder profile renders"    "$FRONTEND/registry/funders/axis-bank-foundation" "Axis Bank Foundation" 90
check_status  "unknown org 404s"           "$FRONTEND/registry/nonexistent-org" 404 60
check_contains "ask preview (signed out)"  "$FRONTEND/ask" "ask-preview" 90
check_redirect "import keeps its destination" "$FRONTEND/import" "next=%2Fimport"
check_status  "resources"                  "$FRONTEND/resources" 200 60
check_status  "copilotkit runtime info"    "$FRONTEND/api/copilotkit/info" 200 30

say "── chat wire (runtime → backend → agent) ────────"
# A cheap end-to-end probe: run a real (tiny) agent turn through the runtime
# path the browser uses. Requires a model API key; counts as one LLM call.
if [[ "${SMOKE_SKIP_LLM:-0}" == "1" ]]; then
  say "  ‣ skipped (SMOKE_SKIP_LLM=1)"
else
  RESP=$(curl -sN --max-time 120 -X POST "$FRONTEND/api/copilotkit/agent/sangam_agent/run" "${AUTH[@]}" \
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
