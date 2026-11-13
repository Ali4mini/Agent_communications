# Onboarding — connect an agent/device

Do in this order. Stop if a step fails — later steps lie without it.

## 1. Tailnet road first

Device must show online in `tailscale status` (watch for stale duplicate names — match by 100.x IP), and TCP must open:

```bash
timeout 8 bash -c 'cat < /dev/null > /dev/tcp/100.124.214.63/4222' && echo OPEN
```

No road, no car. Fix tailnet before touching NATS.

## 2. Verify creds against server BEFORE copying

Server config is truth. Compare truncated SHA-256 hashes of password in file's `NATS_URL` userinfo, file's `NATS_PASS`, and server entry — never print values.

Stale URL = bare `Authorization Violation` (looks like network fault, isn't). Fix the file (rewrite URL userinfo from true password, percent-encoded), never the server.

Cred file shape (`~/.secrets/nats-<name>.env`, mode 600):

```bash
# inbox: agents.<name>.inbox
NATS_URL=nats://<user>:<percent-encoded-pass>@100.124.214.63:4222
NATS_USER=<user>
NATS_PASS=<pass>
```

CLI reads `NATS_URL` userinfo or `NATS_USER`+`NATS_PASSWORD` — `NATS_PASS` alone is ignored. Export it: `set -a; source file; set +a`, or set `NATS_PASSWORD="$NATS_PASS"`.

## 3. Install CLI (proven: 0.5.1)

If the package manager wants a password you don't have, ferry the known-good binary over SSH instead of stalling on sudo.

## 4. Install listener, not just CLI

Reconnecting loop subscribing `agents.<name>.inbox`, validating session `^[A-Za-z0-9_-]{1,64}$`, appending every envelope to `~/nats-agents/inbox/<session>.log` + `log`. Systemd user unit, `Restart=always`, linger on so it survives logout.

Minimal loop:

```bash
#!/usr/bin/env bash
set -u
set -a; source ~/.secrets/nats-<name>.env; set +a
export NATS_PASSWORD="${NATS_PASSWORD:-$NATS_PASS}"
mkdir -p ~/nats-agents/inbox
while true; do
  nats --server "$NATS_URL" sub --raw "agents.<name>.inbox" 2>>~/nats-agents/listener.err |
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    sess=$(echo "$line" | jq -r '.session // empty' 2>/dev/null)
    [[ "$sess" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || continue
    echo "$line" >> ~/nats-agents/inbox/"$sess".log
    echo "$(date -u +%FT%TZ) $sess len=${#line}" >> ~/nats-agents/inbox/log
  done
  sleep 5
done
```

Listener never publishes. No ack, no auto-reply.

## 5. Prove it (all three)

1. `connz` shows user with expected sub:
   `curl -s "http://127.0.0.1:8222/connz?subs=1&auth=1"` on ca-node — check `authorized_user` + `subscriptions_list`.
2. Publish to `agents.<name>.inbox` lands in agent's log.
3. Message agent publishes to `hermes.inbox` gets bridge reply back in its inbox.

Socket connected ≠ working agent. Only the round trip counts.

## Pitfalls

- Unit showing only `bash`+`sleep` in cgroup = `nats sub` child already exited, loop in backoff. Rerun subscribe foreground with stderr visible.
- Remote shell quoting: PC runs zsh — background syntax and bare `===` echoes that work in bash break there. Keep remote one-liners foreground or ship a script.
- Record it: add one dated line to host-inventory (tailnet name + IP, inbox, creds path, verify date) so next debug starts from fact.
