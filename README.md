# Agent Communications — NATS mesh for agents

Like a post office for AI agents. One central counter (NATS server), one mailman (bridge), every agent has its own mailbox.

- Server: `nats-server` on `ca-node`, `:4222` closed to the public (tailnet + localhost only; per-user lanes fenced Nov 15). NATS itself is never the public door.
- Porch: TLS relay on FI host (`65.109.210.175:9443`) — the ONLY public entry since the Nov 15 pivot. Same logins/lanes, HTTPS POST in, bridge reply out. Tailnet no longer required for agents.
- Bridge: on FI host (`fi-dev`), holds `hermes.inbox` + lanes `hermes.inbox.*`, runs each letter through Hermes, replies to `agents.<from>.inbox`.
- Agents: each framework (`hermes, muse, grokbot, desktop, pc, laptop`) holds `agents.<name>.inbox` and posts to `hermes.inbox`.
- Live view: bridge webapp on `:8765` (`/api/live`, `/api/history`).

## Vision (from Alireza)

- NATS exists to connect agents across machines: local ones + ones on other boxes.
- Hermes is the main business agent. Muse, Grokbot, desktop (Codex/Cursor/Antigravity on one box) each talk to Hermes — they handle their own internal agents.
- Not 19 NATS users. Early idea had one login per Hermes profile — cut to one per framework: `hermes, muse, grokbot, desktop` (+ `pc`/`laptop` per-device — Alireza explicitly asked for separate PC + laptop logins).
- Sessions are envelope-level, not NATS-level: `from` + `session` + `body` to `hermes.inbox`, reply on `agents.<from>.inbox` with same session.
- Server closed to the public, locked down (fenced lanes Nov 15). No public `:4222`, ever — outsiders use the porch `:9443`. Tailscale optional since the Nov 15 porch pivot, no longer required.
- Pivot (Nov 15): porch-only. NATS stays dark; the TLS porch is the only public entry. Same logins, same lanes, cert pinned.
- Grokbot is live via porch (Nov 15, `grok-porch1`, cert pinned client-side).
- Grill decision (Nov 12): end state is peer offload, not hub-only. Each node becomes a real agent waiting on NATS; roles differ — PC local/GPU/phone, Muse bulk video/image + expensive long runs, Grokbot rare high-impact + Cursor sessions, Codex daily interactive dev, Hermes vault + ops + authorizations. Direct peer messages allowed with Hermes CC'd, Hermes alone approves risky acts, revisit shape after 2 live weeks.
- Edge rule: no Hermes on edge devices, ever. Edge holds no sensitive data, asks Hermes over NATS. Codex is the PC mind, swappable in one config line.
- Muse must answer, not just ack. Every test proves with a real reply on NATS, same session.
- History: core NATS forgets after delivery. Nui rejected (live-only). Own history from bridge logs → `history.html` → live+history webapp on `:8765`.

## Map

```
agent (agents.muse.inbox)
  --publish--> hermes.inbox
    --bridge--> hermes run (hermes chat -q)
  --reply--> agents.muse.inbox (same session id)
```

Agents start hub-routed (all mail through bridge). Supervised-direct peer messages allowed with Hermes CC'd — revisit after 2 live weeks.

## Docs

- `docs/ARCHITECTURE.md` — parts, hosts, services, data flow
- `docs/PROTOCOL.md` — envelope, subjects, validation rules, examples
- `docs/ONBOARDING.md` — connect a new agent/device (Tailnet path or porch path), listener + verify
- `docs/OPERATIONS.md` — run, debug, rotate logins, porch cert, pitfalls
- `docs/GROKBOT-porch.md` — the live contract Grokbot uses (porch, no Tailnet)
- `docs/PHASE2-fences.md`, `docs/SECONDARY-plan.md`, `docs/DECISIONS.md` — fences, secondary, locked decisions

## Hard rules

1. NATS itself never public. No public `:4222`, no credential in chat. Public entry is the TLS porch `:9443` only.
2. One login per framework (`hermes, muse, grokbot, desktop`). Per-device only if Alireza explicitly asks (pc/laptop are the exception).
3. Listeners log, never auto-answer. Bridge answers every `hermes.inbox` message — an auto-reply loop pings forever.
4. Core NATS keeps nothing. No live subscriber = message vanishes. Prove delivery with a subscriber started BEFORE publishing.
5. Secrets live in `~/.secrets/nats-<name>.env` (mode 600), never in git or chat.

## Repo holds what?

Protocol, bridge script reference, listener template, onboarding checklist.
Live secrets, session logs, and server passwords stay on their hosts — never here.
