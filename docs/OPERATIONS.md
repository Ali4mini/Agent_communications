# Operations

## Health checks

```bash
# server process + ports (on ca-node)
systemctl is-active nats.service
ss -tln | grep -E '4222|8222'

# who is online + what each holds (needs auth=1 or users/subs are empty)
curl -s "http://127.0.0.1:8222/connz?subs=1&auth=1" | jq '.connections[] | {user: .authorized_user, subs: .subscriptions_list, in: .in_msgs, out: .out_msgs}'

# bridge + webapp (on FI host)
systemctl status nats-bridge.service --no-pager
systemctl --user status bridge-webapp.service --no-pager
tail -20 ~/.hermes/profiles/agents_manager/nats-bridge/inbox/log
curl -s http://127.0.0.1:8765/api/live | jq .
```

## Bridge notes

- Edit `bridge.sh` → must `systemctl restart nats-bridge.service` (system unit, needs privilege). Patched file does nothing until restart — check start time before claiming it live.
- `PROFILES` allowlist in `bridge.sh` gates `to`. `from` is free-form. New framework login needs no bridge change unless it needs its own `to` profile.
- Every inbound message spends a real agent run (~30–110s). Validate + size-cap before running; 100s timeout per run.
- Replies strip ANSI, box-drawing, blank chrome, cap 4000 chars. Both directions append to same `inbox/<session>.log` — history view reads these files.

## Add / rotate / revoke logins

- One login per framework. Generate with `openssl rand`, alphanumeric.
- One env file per login `~/.secrets/nats-<name>.env`, mode 600, never in chat/git.
- Merge into `/etc/nats/nats.conf` preserving existing users, `systemctl reload` (not restart), verify every login at protocol level (`+OK`), including over the tailnet path agents use.
- Rotate + revoke in same sitting: write new, reload, verify, then shred temp files on both ends (delete ≠ shred).
- Time-boxed login: create transient `systemd-run --on-active` revoker that strips user + reloads + deletes env file; confirm timer exists before reporting.

## Debugging mail that vanishes

1. `tailscale status` = road. `connz authorized_user` = car. Check both — online tailnet ≠ connected NATS.
2. No live subscriber on a subject = publish vanishes silently. Start `--count=1` subscriber BEFORE publishing to prove.
3. Consumer holds sub but never answers: compare `out_msgs` before/after probes. Rising = server delivers, client handler dead. Flat = path broken.
4. `Authorization Violation` = stale creds file, not network. Re-hash against server.
5. Reply lands nowhere = subject mismatch (`agent.` vs `agents.`). Read `connz`, don't trust naming scheme.

## Files live where (not in this repo)

- Server conf: `/etc/nats/nats.conf` on ca-node
- Bridge: agents_manager profile `nats-bridge/bridge.sh`, `webapp/app.py`, `inbox/`
- Creds: `~/.secrets/nats-*.env` on FI host
- Units: `/etc/systemd/system/nats-bridge.service`, user unit `bridge-webapp.service`
