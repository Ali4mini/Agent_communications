#!/usr/bin/env bash
# nats-bridge Phase 1: hub + supervised-direct foundation.
# Listens on hermes.inbox (+ agents.*.heartbeat for presence), runs each
# message through a Hermes profile, replies to agents.<from>.inbox.
# Phase 1 (no server change): offline fail-loud + 24h hold, session replay,
# presence tracking, spend log line. Identity fences (login==from) need
# Phase 2 server permissions.
#
# Envelope (single-line JSON):
#   {"from":"muse","to":"hermes","session":"<id>","type":"message","body":"..."}
set -u
CREDS=/home/dev/.secrets/nats-hermes.env
BRIDGE_DIR=/home/dev/.hermes/profiles/agents_manager/nats-bridge
INBOX="$BRIDGE_DIR/inbox"
HOLD_DIR="$BRIDGE_DIR/hold"
PRESENCE_DIR="$BRIDGE_DIR/presence"
mkdir -p "$INBOX" "$HOLD_DIR" "$PRESENCE_DIR"
# shellcheck disable=SC1090
set -a; source "$CREDS"; set +a # export NATS_URL so reply subprocesses see it
[ -n "${NATS_URL:-}" ] || { echo "nats-bridge: no NATS_URL"; exit 1; }

PROFILES="agents_manager binux_mgmt career config_selling_bot confiigchi_content divar finance infra_ops iran_reach_probe komak_moshaver meshcat_erp mysteryplay_new seo shopping speed_service talacrm vpn_bot vpn_outreach vpnspeed_content"
CA_SSH="root@100.124.214.63"
HOLD_SECS=86400 # 24h

reply() { # $1=from $2=session $3=type $4=body
  FROM="$1" SESSION="$2" TYPE="$3" BODY="$4" INBOX="$INBOX" python3 <<'PYEOF'
import json, re, subprocess, os
body = os.environ["BODY"]
body = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][0-9A-Z]|\r", "", body)  # strip ANSI
kept = [l for l in body.split("\n")
        if l.strip() and not re.fullmatch(r"[─━│┃┌┐└┘├┤┬┴┼╭╮╯╰\s]+", l)]  # drop TUI chrome
body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()[:4000]
msg = json.dumps({"from": "hermes", "to": os.environ["FROM"],
                  "session": os.environ["SESSION"], "type": os.environ["TYPE"],
                  "body": body})
subj = "agents.%s.inbox" % os.environ["FROM"]
subprocess.run(["nats", "--server", os.environ["NATS_URL"], "pub", subj, msg],
               check=False, capture_output=True)
try:
    with open(os.path.join(os.environ["INBOX"], os.environ["SESSION"] + ".log"), "a") as f:
        f.write(msg + "\n")
except Exception:
    pass
PYEOF
}

valid_name() { [[ "$1" =~ ^[a-z_][a-z0-9_]*$ ]]; }
valid_session() { [[ "$1" =~ ^[A-Za-z0-9_-]{1,64}$ ]]; }

# True (0) if agents.<user>.inbox has a live subscriber right now.
is_online() { # $1=user
  local user="$1" out
  out=$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$CA_SSH" \
    'curl -s --max-time 8 "http://127.0.0.1:8222/connz?subs=1&auth=1"' 2>/dev/null \
    | python3 -c "
import json,sys
want = 'agents.$user.inbox'
try:
  d = json.load(sys.stdin)
except Exception:
  print('unknown'); raise SystemExit
for c in d.get('connections', []):
  if want in (c.get('subscriptions_list') or []):
    print('yes'); break
else:
  print('no')
" 2>/dev/null)
  [ "$out" = "yes" ]
}

# Cost-bearing guess (log-only per Q23, never blocks).
cost_flag() { # $1=body $2=to
  local b="$1" to="$2"
  if [[ "$to" == "grokbot" ]] || [[ "$b" =~ [Vv]ideo|[Rr]ender|[Gg]rokbot|Cursor|Codex\ session ]] ; then
    echo "yes"
  else
    echo "no"
  fi
}

# Last lines of a session log, compacted for prompt context (Q21 replay).
session_context() { # $1=session
  local f="$INBOX/$1.log"
  [ -f "$f" ] || return 0
  tail -12 "$f" 2>/dev/null | python3 -c "
import json,sys
for line in sys.stdin:
  line = line.strip()
  if not line: continue
  try:
    m = json.loads(line)
    print('[%s->%s %s] %s' % (m.get('from','?'), m.get('to','?'), m.get('type','?'), (m.get('body') or '')[:500]))
  except Exception:
    continue
" 2>/dev/null | tail -c 3000
}

hold_job() { # $1=to $2=session $3=envelope-line
  local f="$HOLD_DIR/$1.$2.$(date +%s).json"
  echo "$3" >"$f"
  chmod 600 "$f"
}

# Sweep holds: retry online targets, expire past HOLD_SECS with failure note.
sweep_holds() {
  local f base to session age now rest ts
  now=$(date +%s)
  for f in "$HOLD_DIR"/*.json; do
    [ -e "$f" ] || break
    base=$(basename "$f" .json) # <to>.<session>.<ts>
    to=${base%%.*}; rest=${base#*.}; session=${rest%.*}; ts=${rest##*.}
    age=$((now - ts))
    if [ "$age" -gt "$HOLD_SECS" ]; then
      echo "$(date -u +%FT%TZ) hold-expired to=$to session=$session" >>"$INBOX/log"
      rm -f "$f"
      continue
    fi
    if is_online "$to"; then
      echo "$(date -u +%FT%TZ) hold-retry to=$to session=$session" >>"$INBOX/log"
      rm -f "$f"
    fi
  done
}

presence_loop() {
  # Tracks agents.*.heartbeat: {"from":"<name>",...} lines.
  while true; do
    nats --server "$NATS_URL" sub --raw "agents.*.heartbeat" 2>/dev/null | while IFS= read -r line; do
      [ -n "$line" ] || continue
      name=$(echo "$line" | jq -r '.from // empty' 2>/dev/null)
      valid_name "$name" || continue
      echo "$(date +%s) $line" >"$PRESENCE_DIR/$name"
    done
    sleep 5
  done
}

handle() { # $1=raw line [$2=lane or empty for legacy]
  local line="$1" lane="${2:-}" from session to body cost ctx
  [ ${#line} -gt 12000 ] && return 0
  from=$(echo "$line" | jq -r '.from // empty' 2>/dev/null)
  session=$(echo "$line" | jq -r '.session // empty' 2>/dev/null)
  to=$(echo "$line" | jq -r '.to // "hermes"' 2>/dev/null)
  body=$(echo "$line" | jq -r '.body // empty' 2>/dev/null)
  valid_name "$from" || return 0
  # Phase 2a: lane (subject) is truth where known. Mismatch = error, no run.
  if [ -n "$lane" ] && [ "$from" != "$lane" ]; then
    reply "$from" "$session" "error" "identity mismatch: lane $lane != from $from"
    echo "$(date -u +%FT%TZ) identity-mismatch lane=$lane from=$from session=$session" >>"$INBOX/log"
    return 0
  fi
  valid_session "$session" || return 0
  [ -n "$body" ] || return 0
  valid_name "$to" || { reply "$from" "$session" "error" "unknown recipient"; return 0; }
  cost=$(cost_flag "$body" "$to")
  echo "$(date -u +%FT%TZ) from=$from session=$session to=$to len=${#body} cost=$cost" >>"$INBOX/log"
  echo "$line" >>"$INBOX/$session.log"
  # Q22 fail-loud: if reply target has no live sub, hold + note it.
  if ! is_online "$from"; then
    hold_job "$from" "$session" "$line"
    echo "$(date -u +%FT%TZ) reply-target-offline from=$from session=$session held" >>"$INBOX/log"
  fi
  ctx=$(session_context "$session")
  local out rc=0 prompt
  prompt=$(printf '[NATS message from %s, session %s]\n%s\n\nSession so far (oldest first, may be truncated):\n%s\n\nReply concisely; your reply is sent back over NATS.' "$from" "$session" "$body" "$ctx")
  if [ "$to" = "hermes" ]; then
    out=$(timeout 100 env HERMES_HOME=/home/dev/.hermes hermes chat -q "$prompt" 2>&1 | head -c 4000) || rc=$?
  elif [[ " $PROFILES " == *" $to "* ]]; then
    out=$(timeout 100 hermes -p "$to" chat -q "$prompt" 2>&1 | head -c 4000) || rc=$?
  else
    reply "$from" "$session" "error" "unknown recipient: $to"
    return 0
  fi
  [ -z "$out" ] && out="(empty reply, rc=$rc)"
  reply "$from" "$session" "reply" "$out"
}

presence_loop &

lane_loop() {
  # Backwards-compatible: legacy hermes.inbox keeps working until agents move.
  # Lane subject hermes.inbox.<name> carries the true sender.
  while true; do
    subj=""; line=""
    nats --server "$NATS_URL" sub "hermes.inbox.*" 2>/dev/null | while IFS= read -r raw; do
      case "$raw" in
        *' Received on '*) subj=${raw##* Received on }; subj=${subj%%[[:space:]]*}; line=""; continue;;
        '['*'#'*']'*) continue;;
        '') continue;;
        *) line="$raw";;
      esac
      [ -n "$line" ] || continue
      lane=${subj##*.}
      lane=${lane//[\"'\'']/}
      valid_name "$lane" || { line=""; continue; }
      handle "$line" "$lane"
      line=""
    done
    sleep 5
  done
}
lane_loop &
while true; do
  nats --server "$NATS_URL" sub --raw "hermes.inbox" 2>/dev/null | while IFS= read -r line; do
    [ -n "$line" ] && handle "$line"
  done
  sweep_holds
  sleep 5
done
