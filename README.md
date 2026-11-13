# Agent Communications — NATS mesh for agents

Like a post office for AI agents. One central counter (NATS server), one mailman (bridge), every agent has its own mailbox.

- Server: `nats-server` on `ca-node`, tailnet-only `:4222`. Only machines on the tailnet can reach it.
- Bridge: on FI host (`fi-dev`), holds `hermes.inbox`, runs each letter through Hermes, replies to `agents.<from>.inbox`.
- Agents: each framework (`hermes, muse, grokbot, desktop, pc, laptop`) holds `agents.<name>.inbox` and posts to `hermes.inbox`.
- Live view: bridge webapp on `:8765` (`/api/live`, `/api/history`).

## Map

```
agent (agents.muse.inbox)
  --publish--> hermes.inbox
    --bridge--> hermes run (hermes chat -q)
  --reply--> agents.muse.inbox (same session id)
```

Agents never talk to each other directly. All mail goes through the bridge.

## Docs

- `docs/ARCHITECTURE.md` — parts, hosts, services, data flow
- `docs/PROTOCOL.md` — envelope, subjects, validation rules, examples
- `docs/ONBOARDING.md` — connect a new agent/device, listener + verify
- `docs/OPERATIONS.md` — run, debug, rotate logins, pitfalls

## Hard rules

1. Server stays tailnet-only. No public `:4222`, no credential in chat.
2. One login per framework (`hermes, muse, grokbot, desktop`). Per-device only if Alireza explicitly asks (pc/laptop are the exception).
3. Listeners log, never auto-answer. Bridge answers every `hermes.inbox` message — an auto-reply loop pings forever.
4. Core NATS keeps nothing. No live subscriber = message vanishes. Prove delivery with a subscriber started BEFORE publishing.
5. Secrets live in `~/.secrets/nats-<name>.env` (mode 600), never in git or chat.

## Repo holds what?

Protocol, bridge script reference, listener template, onboarding checklist.
Live secrets, session logs, and server passwords stay on their hosts — never here.
