# Decisions — grill rounds (locked)

## Nov 12 grill (main chat)
- Roles: PC local/GPU/phone, Muse bulk video/image + expensive long runs, Grokbot rare high-impact + Cursor, Codex daily interactive dev, Hermes vault + ops + authorizations.
- Each node becomes a real agent on NATS; responsibilities differ. Hermes alone holds authorizations.
- Task lifecycle: id + ack + result-or-timeout, Hermes fallback.
- Supervision: direct peer messages with Hermes CC'd for now, revisit after 2 live weeks.
- Guardrails: TTL + spend ceiling agreed in principle.
- Edge: no Hermes on edge, Codex is PC mind and swappable, one contract for all minds.

## Nov 13 grill round 3 (this chat)
- Q19 locked: PC runs NATS jobs as background Codex runs; live session always wins; queue only on same-folder clash. TODO when building PC listener: lock in method to detect active Codex sessions.
- Q20 locked: open inbox — any peer may send PC work; cost-bearing needs Hermes pre-approval; PC holds veto.
- Q21 locked (revised): session id = task id; timeout never kills a session, only quiets it; same id resumes with replayed context (required for memoryless Codex/Cursor).
- Q22 locked: offline fail-loud — target with no live sub gets `error` "offline, retry later"; Hermes holds instead of firing blind. (To implement in bridge.)
- Q23 locked: spend cap log-only for now, enforce later. Bridge logs cost-bearing jobs without blocking.
- Higher-level (Nov 13): onboarding stays manual — Alireza alone adds/kicks agents, no join-request flow needed for now.
- Routing intent (Nov 13): not token metering — route by task type + Alireza's experience of fit (PC local/GPU/phone, Muse video/image + heavy long runs, Grokbot hard/rare, Codex daily dev, Hermes ops/vault).
- Heartbeat (Nov 13): `nats-heartbeat` cron every 10m — checks :4222, connz, bridge + webapp; shouts only on failure.
- Secondary (due Nov 16): thin Hermes (memory synced, no full tools, weaker box OK) + secondary NATS/bridge. Reminder set.
- Log hygiene (Nov 14): keep full logs forever — no scrub, no expiry. Alireza's call; secrets stay in bridge session logs.
- Offline holding (Nov 14): Hermes holds offline-bound jobs 24h, retries on reappear; past 24h replies failed to sender.
- Big artifacts (Nov 14): pointer only — path/URL + hash in envelope, receiver fetches; never inline bytes.
- Identity (Nov 14): bridge enforces login-name == from field; mismatch gets error, no run.
