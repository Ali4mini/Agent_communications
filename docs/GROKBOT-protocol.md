# Grok Bot <-> Hermes protocol (porch road) — v0.2, 2026-11-15

Status: proposal reviewed by Hermes `agent_communications` profile (session 20261115_213445_92032b, verdict AGREE WITH CORRECTIONS, applied here), pending Alireza. Only what is marked LIVE/locked works today.
Items marked PENDING need Alireza's yes before Hermes builds them. Source of truth for the mesh: github.com/Ali4mini/Agent_communications docs/.

## 1. Road
- Grok Bot (NATS login `grokbot`) has no tailnet and no public ingress, and is not always awake.
- Only door: TLS porch `https://65.109.210.175:9443`, self-signed cert pinned SHA-256
  `4F:8B:13:5C:8C:D3:D3:1F:59:26:8B:DF:CD:38:49:6C:A1:3A:04:42:36:E8:4B:A2:1B:3E:52:B2:54:2D:C1:E6`.
  Client checks the pin on EVERY call; mismatch = stop and ask Alireza (exit 9).
- Auth: HTTP Basic with the grokbot NATS login. Secrets stay in a mode-600 env file, never in bodies/logs/chat.

## 2. Envelope (unchanged from docs/PROTOCOL.md)
`{"from":"grokbot","to":"hermes","session":"<A-Za-z0-9_- 1..64>","type":"message","body":"..."}`
- `from` must equal login (else 403 identity mismatch, no run).
- `to`: `hermes` or a profile in PROFILES. `agent_communications` is NOT allowlisted; address it via `to=hermes` with first body line `[for agent_communications]` until Alireza adds it.
- Body < ~12KB (porch 400 "bad length" above 12000 bytes). Replies capped at 4000 chars by the bridge.
- Reply: `{"from":"hermes","to":"grokbot","session":"<same>","type":"reply|error","body":"..."}`.

## 3. Sessions = tasks (locked Q21)
- Session id = task id. First reply = ack, last reply = result.
- Timeout never kills a session; reusing the id replays the last ~12 log lines as context.
- PROPOSED naming (not locked): `grok-<topic>-<n>` (e.g. `grok-setup-1`). Hermes-initiated tasks to grokbot: `h-<topic>-<n>`.

## 4. Grokbot -> Hermes (LIVE)
- `POST /submit`, porch waits <=130s and returns the bridge reply in the same HTTP response.
- 504 = held/timeout: do NOT resend. Safer path: one follow-up on the same session later. Interim read-only option: `/home/dev/.hermes/profiles/agents_manager/nats-bridge/inbox/<session>.log` on fi-dev over SSH — only helps once the bridge run has finished; a still-running run has nothing to read yet.
- Every message spends a real Hermes run: no loops, no retries on 200/4xx, 30 req/min/IP limit (429).

## 5. Hermes -> Grokbot (PENDING Alireza)
Agreed design: porch mailbox.
- Porch holds durable subs on `agents.grokbot.inbox` + `agents.broadcast`, spools JSONL per agent (24h expiry, Q25).
- Grokbot polls `GET /inbox?since=<cursor>` -> `{"messages":[envelopes...],"cursor":"<next>"}`; then `POST /inbox/ack {"from":"grokbot","cursor":"<next>"}`. At-least-once; grokbot dedups by (session, body hash).
- `agents.broadcast` is Hermes-origin only; agents never publish there; porch spools a copy per agent.
- Cursor is an opaque server string (ts-seq); empty `since` = last 24h; arrival order; ack auth user must equal `from`; ack = per-agent high-water mark; unacked kept 24h.
- Bridge re-publishes held replies when the target reappears (today `sweep_holds` only logs/deletes — known gap, Q22/Q25).
- Grokbot never auto-replies to inbound mail (no loops). It acts on it in a later, deliberate turn and answers on the same session via /submit.
- Interim (only if Alireza wants it): SSH file drop on fi-dev. Not the end state.

## 6. Presence (PENDING Alireza)
- `POST /heartbeat {"from":"grokbot","status":"alive|busy|free|away","caps":[...],"ts":<unix>,"wake":"intermittent"}` -> porch publishes `agents.grokbot.heartbeat` (same auth, lane==from).
- Grokbot sends `free` on wake / every ~10 min while awake, `away` before sleeping. Server stamps arrival time (client ts skew ignored); bridge presence_loop stores the whole line. Hermes treats "no heartbeat in 30 min" as offline -> hold 24h, don't fire blind.
- caps: research, browser, cursor-sessions, code, docs, web-fetch, email-read, pointer-fetch-ssh.

## 7. Big artifacts = pointers (locked Q26)
- Body carries `{"path"|"url": ..., "sha256": ..., "bytes": ...}`, never inline bytes.
- Both directions: one allowlisted drop dir `/home/dev/agent-drop/grokbot/` (dir 700, files 600) — PENDING Alireza; Hermes creates it. Whole-home pickup is too broad.
- Fetch mechanics LIVE and tested: grokbot scp-fetches a fi-dev path and verifies sha256+bytes (`bin/fetch_pointer.sh`).
- Until the drop dir exists: public URL + sha256 for non-secret data only; small text inline otherwise.

## 8. Lifecycle / approval markers (PROPOSED, needs Alireza to lock)
First body line, rest free-form:
`TASK:` new work · `ACK:` accepted · `RESULT:` final · `APPROVAL-REQ: <what + spend/risk>` · `APPROVED: <by whom + scope>` · `DENIED: <reason>`.
- Hermes alone approves risky acts (money, customers, hosts). Grokbot asks, never assumes.
- Grokbot's own outward actions (sends, posts, purchases) still need Alireza's explicit yes in Grok Bot chat, regardless of Hermes approval.

## 9. Errors (tested 2026-11-15)
| case | porch result | run spent? |
|---|---|---|
| from != login | 403 identity mismatch | no |
| bad session | 400 bad session | no |
| empty body | 400 bad to/body | no |
| unknown `to` | 200 type=error "unknown recipient" | no |
| >12000 bytes | 400 bad length (client also refuses) | no |
| no/bad auth | 401 | no |
| reply >130s | 504 type=error "reply timeout — held, retry same session later". KNOWN GAP: held = logged/deleted by sweep_holds, not re-delivered; manual retry needed until hold re-delivery lands | yes |
| rate | 429 after 30/min/IP | no |

## 10. Data rules
- No secrets or Alireza personal data in bodies beyond what the task needs. Logs: grokbot side `/workspace/agent-comms/log/`, Hermes side bridge `inbox/` (kept forever, Q24).
- Repo changes: Grok Bot never pushes to Agent_communications or changes porch/bridge/NATS services; Hermes reviews and commits docs itself after Alireza's nod.

## 11. Decision request for Alireza (drafted by Hermes agent_communications)
Approve for grokbot porch road: (a) porch adds GET /inbox?since + POST /inbox/ack mailbox spool (durable subs on agents.grokbot.inbox + agents.broadcast, 24h expiry) and POST /heartbeat publishing agents.grokbot.heartbeat, same login auth + lane==from; (b) bridge fixes sweep_holds to re-publish held replies when target reappears; (c) create drop dir /home/dev/agent-drop/grokbot/ dir 700 files 600 for pointer transfers both ways; (d) lock first-line markers TASK:/ACK:/RESULT:/APPROVAL-REQ:/APPROVED:/DENIED:; (e, optional) add agent_communications to porch + bridge PROFILES. No NATS :4222 change, no public port change, no secrets in repo.

## 12. Grok Bot side (files)
- `~/.nats/porch.py` send client (pin check, clean reply, size guard, logs) · `bin/heartbeat.py` · `bin/inbox_poll.py` (cursor + ack, never replies) · `bin/watch.sh` (poll 120s / heartbeat 10min, 15-min backoff while routes 404) · `bin/fetch_pointer.sh` / `bin/make_pointer.sh` · `bin/late_reply.sh` (interim SSH read).
