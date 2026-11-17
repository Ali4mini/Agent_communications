# Secondary build plan — de-tgbot (Nov 17)

## Box choice (locked)
**de-tgbot** `100.125.66.75` (`srv2794780455`): 2 vCPU, ~1.9 GB available, 49 GB free, Debian 13, tailnet member, no ports conflict, NATS not installed. `hetzner-de` dark; `de-exit` only 432 MB free. Run as root via tailnet (host key accepted to temp known_hosts — verify fingerprint with Alireza before trusting long-term).

## What goes where
```
de-tgbot:
  nats.service          — own NATS, :4222 tailnet-only, SEPARATE from primary (no clustering)
  nats-bridge.service   — owns its own hermes.inbox + lanes, talks to its own NATS
  thin Hermes           — memory snapshot pulled daily from FI (rsync/tar over SSH), read-only, no vault/tools
  porch NOT replicated  — primary porch on FI stays the only public door
```

## Failover (locked: tailnet-name flip)
- Agents use a stable tailnet name; a small check flips it to whichever host's heartbeat is healthy.
- Secondary stays warm/standby: its bridge runs but primary porch still routes to FI until flip.

## Memory sync (locked: daily)
- Nightly cron pulls a snapshot of primary Hermes memory/skills → de-tgbot read-only. Thin Hermes never writes main.

## Steps
1. [ ] Verify host key fingerprint with Alireza; add to known_hosts.
2. [ ] Install nats-server + nats CLI 0.5.1 on de-tgbot.
3. [ ] Copy conf pattern (own users — separate passwords or same? **ask Alireza**), tailnet firewall, start nats.service.
4. [ ] Install thin Hermes (no vault, no tools beyond read) + daily sync job.
5. [ ] Deploy bridge.sh with its own creds + unit.
6. [ ] Failover script + tailnet name.
7. [ ] Prove: publish to secondary lane → reply back; flip drill.

## Open pick
- NATS users on secondary: reuse the same logins (simplest, but primary credentials copied) OR fresh secondary set. Need Alireza's call.
