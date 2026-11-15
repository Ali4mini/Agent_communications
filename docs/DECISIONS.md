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
- Presence (Nov 14): every agent posts heartbeat — alive, busy/free, capabilities. Hermes assigns only to live + free + capable.
- Pivot (Nov 15): porch-only. NATS stays dark; TLS porch `:9443` is the only public entry; Tailnet no longer required.
- Porch live (Nov 15): HTTPS relay, sender-identity, 130s reply wait, rate-limited, pinned cert. Proven with grokbot round-trip.
- Grokbot live (Nov 15): `grok-porch1`, GROK_PORCH_OK, cert pinned + client-side pinning. First external agent on the mesh.
- Reply trim (Nov 15): bridge strips Hermes CLI chrome (banner, Query echo, resume block, session footer) — replies arrive clean.
- Mailbox round (Nov 15, Alireza-approved via grokbot relay): porch mailbox live — durable spool of agents.grokbot.inbox (24h expiry), GET /inbox?since + POST /inbox/ack, POST /heartbeat (presence-file fallback, NATS heartbeat publish is fence-denied). Bridge re-publishes held replies on reappear (live sub, or fresh heartbeat/poll for porch sleepers). Drop dir /home/dev/agent-drop/grokbot/ (700/600). Lifecycle markers locked: TASK:/ACK:/RESULT:/APPROVAL-REQ:/APPROVED:/DENIED:. agent_communications added to porch + bridge PROFILES allowlists.
- Fence findings (Nov 15, no server change): under live per-user lanes, hermes can publish agents.*.inbox (replies + Hermes-originated mail work) but cannot sub agent inboxes/broadcast; grokbot can sub only its own inbox. agents.broadcast and NATS heartbeat publish are unusable today — broadcast arrives as per-agent inbox copies spooled by the porch; heartbeat lands via presence file. Revisit if fences ever open those subjects.
