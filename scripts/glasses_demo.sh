#!/usr/bin/env bash
# The three stage beats of the glasses demo, over curl, with `transcript=`
# instead of audio (ADR 0036, plans/glasses-endpoints-2026-08-26.md).
#
#   API=https://<backend> JWT=<mops staff jwt> TASK=<cleaning task id> ./scripts/glasses_demo.sh
#
# The tenant needs mops_config.glasses.enabled = true, and the JWT a staff
# member who is on that clean (beat 3 needs can_inspect). Every call is a
# door a thumb could open — nothing here is demo-only.
set -euo pipefail

: "${API:?set API to the backend origin, e.g. https://millia-dev.fly.dev}"
: "${JWT:?set JWT to a MOPS staff bearer token}"
: "${TASK:?set TASK to the cleaning task id the wearer is on}"

say() {
  local text="$1"; shift
  echo
  echo "▶ \"$text\""
  curl -sS -X POST "$API/api/v1/glasses/say" \
    -H "Authorization: Bearer $JWT" \
    -F "transcript=$text" \
    -F "task_id=$TASK" \
    -F "client_request_id=$(uuidgen | tr '[:upper:]' '[:lower:]')" \
    "$@" | python3 -c 'import json,sys; c=json.load(sys.stdin); print("  say:    ", c["say"]); print("  show:   ", c["display"]["ambient"]); print("  intent: ", c["intent"], "| mode:", c["mode"], "| needs:", c["needs"], "| capture:", c["capture"])'
}

echo "── who am I, what am I on"
curl -sS "$API/api/v1/glasses/context?task_id=$TASK" -H "Authorization: Bearer $JWT" \
  | python3 -c 'import json,sys; c=json.load(sys.stdin); print("  me:     ", c["me"]); print("  mode:   ", c["mode"]); print("  say:    ", c["say"])'

echo; echo "── beat 1: clean a room hands-free"
say "Millia, start work"
say "Millia, done"
say "Millia, next step"
say "Millia, what step am I on?"

echo; echo "── beat 2: report a fault without stopping"
say "Millia, report: the bedside lamp is not working"

echo; echo "── beat 3: inspector (needs a completed clean + can_inspect)"
say "Millia, take the photo"
say "Millia, redo — water spots on the mirror" -F "photo_url=https://example.invalid/shot.jpg"

echo; echo "── the same step in Malay (with audio the reply comes back in the spoken language; with transcript= it uses the profile locale)"
say "Millia, seterusnya"
