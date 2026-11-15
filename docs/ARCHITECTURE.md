# Architecture

## Parts

**1. Server — ca-node (`100.124.214.63`)**
- `nats.service`, active. Listens `0.0.0.0:4222`, monitor `127.0.0.1:8222` (localhost only).
- Firewall: localhost + tailnet (`100.64.0.0/10` v4, `fd7a:115c:a1e0::/48` v6) ACCEPT on `:4222`, DROP rest. Same for v6 loopback.
- Config: `/etc/nats/nats.conf`. Auth required, one user per framework. `max_connections: 1024`.
- Source of truth for passwords. Fix files from server, never server from files.

**2. Bridge — FI host (`fi-dev`, `100.92.180.92`)**
- Code: `nats-bridge/bridge.sh` (reference copy; live copy runs from agents_manager profile).
- Unit: `nats-bridge.service` (system unit, `Restart=always`). Starts `bridge.sh`.
- What it does: `sub --raw hermes.inbox` → validate → `hermes [-p <to>] chat -q` under 100s timeout → strip ANSI/TUI chrome → `pub agents.<from>.inbox` with same session → append both directions to `inbox/<session>.log`.
- Needs `NATS_URL` exported (`set -a; source creds`) so reply subprocesses inherit it. Needs PATH with Hermes launcher or runs fail.
- Inbox logs: `inbox/<session>.log` (full envelopes both ways) + `inbox/log` (one line per request: time, from, session, to, len).

**3. Webapp — FI host**
- Code: `nats-bridge/webapp/app.py` (stdlib only, no deps).
- Unit: `bridge-webapp.service` (user unit), port `8765` from `BRIDGE_WEBAPP_PORT`.
- `/` = dashboard, `/api/live` = connz snapshot (5s cache), `/api/history` = session logs.
- Live shows who is online now. History shows past sessions from bridge logs. Core NATS itself forgets everything after delivery.

**3. Porch — FI host (pivot Nov 15, the only public door)**
- Code: `porch/server.py` (stdlib, TLS on `:9443`), unit `porch.service` (user unit, enabled, linger on). Cert `porch/porch.crt` (self-signed, fingerprint pinned in `docs/GROKBOT-porch.md`).
- What it does: HTTPS `POST /submit` with basic auth (same NATS login) → validates (`from` == login, session, allowlisted `to`) → publishes as the sender into lane `hermes.inbox.<from>` → waits ≤130s on `agents.<from>.inbox` for the same session → returns the bridge reply. Rate limit 30/min/IP + `GET /health`, `GET /fingerprint`.
- NATS stays dark: `:4222` closed to the public, porch reaches it over the private path. Tailnet no longer required for agents.

**4. Agent side (two roads)**
- Each agent holds one subscription: `agents.<name>.inbox` (except bridge which holds `hermes.inbox`).
- Creds: `~/.secrets/nats-<name>.env` on FI host, mode 600. Contains `NATS_URL` (with userinfo), `NATS_USER`, `NATS_PASS`. CLI uses `NATS_URL` userinfo or `NATS_USER` + `NATS_PASSWORD` — not `NATS_PASS` alone.
- Listener: reconnecting `nats sub` loop as systemd user unit (`Restart=always` + linger), validates session shape, appends to `~/nats-agents/inbox/<session>.log` + `log`. Never publishes back.

## Data flow

1. Agent publishes single-line JSON to `hermes.inbox`.
2. Bridge validates names/session/size, logs request.
3. Bridge runs Hermes (`hermes` or `hermes -p <to>`) with `[NATS message from <from>, session <id>]` prefix.
4. Bridge cleans output (ANSI, box-drawing, empty lines, cap 4000 chars) and publishes `{"from":"hermes","to":"<from>","session":"<same>","type":"reply|error","body":"..."}` to `agents.<from>.inbox`.
5. Unknown `to` gets `error` reply with no agent run. Oversize (>12KB) or bad names/sessions are dropped silently.

## Known live layout (Nov 2026)

- Server: `nats.service` active on ca-node.
- Bridge + webapp: both active since 2026-11-12 on fi-dev.
- Logins on file: `hermes, muse, grokbot, desktop, pc, laptop` (see OPERATIONS for rotation).
- Live subscribers checked via `connz?subs=1&auth=1` — without `auth=1` users/subs come back empty.
