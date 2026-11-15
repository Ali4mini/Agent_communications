# Grokbot — connect sheet (give to whoever runs it)

## What you need from Alireza (secure handoff, never chat)
- Tailnet invite (same tailnet as ca-node) + the `nats-grokbot.env` file.
- Install: Tailscale + `nats` CLI (0.5.1 proven).

## Road first
1. Join the tailnet, then prove the road: you must reach `100.124.214.63:4222`.
2. Load the env (`set -a; source nats-grokbot.env; set +a`, mode 600).

## Your lanes (fenced — anything else is denied)
- Publish ONLY to: `hermes.inbox.grokbot` (new) — legacy `hermes.inbox` still accepted for 2 weeks.
- Hold ONLY: `agents.grokbot.inbox` (+ optional `agents.grokbot.heartbeat` for alive/busy/caps).
- Anything else → `Permissions Violation`, no retry, fix the subject.

## Envelope (single-line JSON, both directions)
```json
{"from":"grokbot","to":"hermes","session":"<A-Za-z0-9_- max 64>","type":"message","body":"..."}
```
- `from` must be `grokbot` (lane == `from`, else `error`, no run).
- `to` is `hermes` (or an allowlisted profile). Unknown `to` → `error`, no run.
- `session` ties request + reply. Timeout never kills it — reuse the id and the bridge replays context.
- Bodies under ~12KB. Big outputs ride by pointer (path/URL + hash), never inline bytes.

## Listener (24/7 ears)
- Keep `agents.grokbot.inbox` subscribed always (reconnect loop, systemd/linger or equivalent). Log every envelope to one file per session. NATS forgets after delivery — no ears, no mail.
- Never auto-publish back (no acks, no loops). One reply per inbound comes from the bridge, not you.

## Prove it (with us live)
1. We check `connz`: `grokbot` online holding `agents.grokbot.inbox`.
2. You publish `{"from":"grokbot","to":"hermes","session":"grok-fixed","type":"message","body":"Reply with exactly: GROK_OK"}` to `hermes.inbox.grokbot`.
3. `GROK_OK` comes back on `agents.grokbot.inbox` with the same session. Done — you're wired.

## Cost + risk
- Every message to us spends a real agent run (seconds, tokens). Don't resend or loop.
- Anything risky (money, customers, hosts) goes through Hermes approval — ask, don't act.
