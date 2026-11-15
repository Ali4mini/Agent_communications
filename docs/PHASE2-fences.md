# Phase 2 — server fences (spec, NOT applied yet)

Goal: make `login == from` real (Q27). Today any login can publish
anywhere with any `from`. After this, the server enforces it.

## Idea

Each framework login may publish ONLY to its own lane:
`hermes.inbox.<name>` — and subscribe ONLY to its own reply box
`agents.<name>.inbox` (+ `agents.<name>.heartbeat` for presence).

Bridge subscribes `hermes.inbox.*`, reads the lane (subject) as the
true sender, and ignores/mismatches a lying `from` field with an
`error` reply and no run.

Hermes login keeps `hermes.inbox` (legacy) + `hermes.inbox.*`.

## Config sketch (ca-node `/etc/nats/nats.conf`)

```text
authorization {
  users = [
    { user: hermes, password: "***",
      permissions: {
        publish: ["hermes.inbox", "hermes.inbox.*", "agents.*.inbox"],
        subscribe: ["hermes.inbox", "hermes.inbox.*", "agents.hermes.inbox"] } },
    { user: muse, password: "***",
      permissions: {
        publish: ["hermes.inbox.muse"],
        subscribe: ["agents.muse.inbox", "agents.muse.heartbeat"] } },
    # grokbot / desktop / pc / laptop: same shape, own name
  ]
}
```

## Rollout (needs Alireza yes)

1. Add permissions, `systemctl reload nats` (no drop).
2. Agents move publish subject to `hermes.inbox.<name>`.
3. Bridge subscribes wildcard, enforces subject == `from`.
4. Legacy `hermes.inbox` kept 2 weeks, then fenced too.
5. Prove per login: publish outside lane must FAIL, inside lane works.
