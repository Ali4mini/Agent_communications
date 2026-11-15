#!/usr/bin/env bash
# pc-listener: 24/7 ears on the PC. Holds agents.pc.inbox open, logs every
# envelope, queues same-folder clashes, runs background Codex for the rest.
# (Draft — clash-detector method still to lock in with Alireza.)
set -u
CREDS=~/.secrets/nats-pc.env
INBOX=~/nats-agents/inbox
QUEUE=~/nats-agents/queue
mkdir -p "$INBOX" "$QUEUE"
set -a; source "$CREDS"; set +a
export NATS_PASSWORD="${NATS_PASSWORD:-$NATS_PASS}"

# Locked (Nov 15): ask Codex itself before each job.
codex_active_folders() {
  codex status --folders 2>/dev/null || codex status 2>/dev/null
}

is_clash() { # $1=body
  local folders f
  folders=$(codex_active_folders)
  [ -z "$folders" ] && return 1
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [[ "$1" == *"$f"* ]] && return 0
  done <<<"$folders"
  return 1
}

queue_job() { # $1=session $2=line
  echo "$2" >"$QUEUE/$1.$(date +%s).json"
  chmod 600 "$QUEUE/$1."*.json 2>/dev/null
}

while true; do
  nats --server "$NATS_URL" sub --raw "agents.pc.inbox" 2>>~/nats-agents/listener.err |
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    sess=$(echo "$line" | jq -r '.session // empty' 2>/dev/null)
    [[ "$sess" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || continue
    echo "$line" >>"$INBOX/$sess.log"
    body=$(echo "$line" | jq -r '.body // empty' 2>/dev/null)
    if is_clash "$body"; then
      queue_job "$sess" "$line"
      echo "$(date -u +%FT%TZ) $sess queued (same-folder clash)" >>"$INBOX/log"
      continue
    fi
    # Background Codex run goes here (never hijacks live session).
    echo "$(date -u +%FT%TZ) $sess ready for background Codex" >>"$INBOX/log"
  done
  sleep 5
done
