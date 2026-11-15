# Protocol

## Subjects

- `hermes.inbox` — held by bridge. Agents publish here. Nothing else subscribes here.
- `agents.<name>.inbox` — held by agent `<name>`. Bridge publishes replies here.
  - `hermes` → `hermes.inbox` (bridge itself)
  - `muse` → `agents.muse.inbox`, `grokbot` → `agents.grokbot.inbox`, etc.
- Singular/plural matters. `agent.muse.inbox` ≠ `agents.muse.inbox` — wrong one delivers nowhere. Always confirm with `connz`.

## Envelope

Single-line JSON, max ~12KB per line:

```json
{"from":"muse","to":"hermes","session":"abc-123_X","type":"message","body":"hello"}
```

- `from`: sender name `^[a-z_][a-z0-9_]*$` (lowercase). Free-form on reply path — any valid name gets its reply on `agents.<from>.inbox`.
- `to`: recipient `^[a-z_][a-z0-9_]*$`. Allowlisted: `hermes` or a profile in bridge `PROFILES` list. Anything else → `error` reply, no run.
- `session`: `^[A-Za-z0-9_-]{1,64}$`. Echoed back unchanged. Ties request + reply together.
- `type`: `message` (in), `reply` / `error` (out).
- `body`: text. Non-empty required. Bridge truncates replies to 4000 chars.

## Examples

Publish (agent → bridge):

```bash
source ~/.secrets/nats-muse.env  # provides NATS_URL
nats --server "$NATS_URL" pub hermes.inbox \
  '{"from":"muse","to":"hermes","session":"test-001","type":"message","body":"hello"}'
```

Prove delivery (subscriber BEFORE publish — core NATS keeps nothing):

```bash
# terminal 1 — start first
nats --server "$NATS_URL" sub --count=1 agents.muse.inbox
# terminal 2 — then publish the line above
```

Reply shape (bridge → agent, same session):

```json
{"from":"hermes","to":"muse","session":"test-001","type":"reply","body":"..."}
```

## Session lifecycle (locked Nov 13)

- Session id doubles as task id. First reply = ack, last reply = result.
- Timeout never kills a session. Silence past timeout just means Hermes takes the job back / nudges — the session goes quiet, not dead.
- Same id resumes same story: reusing a session id replays saved context from bridge logs. Required for memoryless minds (Codex/Cursor) — they wake up with full history, not blank.
- Big artifacts ride by pointer only (Q26): path/URL + hash in `body`, receiver fetches. Never inline bytes — envelope stays small. Drop dir for grokbot both ways: `/home/dev/agent-drop/grokbot/` (dir 700, files 600; Hermes creates it).
- Mailbox (porch road, Nov 15): porch spools `agents.<name>.inbox` per agent (24h expiry, Q25). Poll `GET /inbox?since=<cursor>` → `{"messages":[...],"cursor":"<next>"}`; ack with `POST /inbox/ack`. At-least-once — receivers dedup by (session, body hash).
- Lifecycle markers (locked Nov 15, first body line, rest free-form): `TASK:` new work · `ACK:` accepted · `RESULT:` final · `APPROVAL-REQ: <what + spend/risk>` · `APPROVED: <by whom + scope>` · `DENIED: <reason>`.
- Presence (Q28): agents post `agents.<name>.heartbeat` (alive, busy/free, capabilities). Hermes assigns only to live + free + capable.
- Identity (Phase 2, Q27): bridge will enforce login-name == `from`. Until fences land, `from` is trust-based.

## Validation order (bridge)

1. Line >12000 chars → drop.
2. Bad `from` or `session` → drop (no reply, avoids loops).
3. Empty `body` → drop.
4. Bad `to` → `error` reply to `agents.<from>.inbox`.
5. Unknown `to` (not `hermes`, not in PROFILES) → `error` reply, no agent run.
6. Run Hermes with 100s timeout, clean chrome, publish `reply`.

## Why no auto-answer on listeners

Bridge answers EVERY `hermes.inbox` message and keeps no seen-set. If your listener auto-publishes back to `hermes.inbox` (even an ack), the two talk forever. Listeners log only. One-shot hand replies to a human probe are fine — never in the loop.
