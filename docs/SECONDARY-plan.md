# Secondary stack plan (due Nov 16)

## Thin Hermes

- Same memory (synced), NO full tools/secrets. Asks main Hermes over NATS for anything sensitive.
- Runs on a weaker box (1-2 vCPU OK). Holds no customer data at rest.
- Sync: periodic memory snapshot pull from main (read-only), never push.

## Secondary NATS + bridge

- Second `nats-server` tailnet-only on the same weak box (or neighbor).
- Second bridge subscribing the same `hermes.inbox.*` lanes (active-standby:
  secondary stays quiet unless primary heartbeat dies >2 min).
- Heartbeat already watches primary; add secondary to the same check.

## Open picks (need Alireza)

- Which box hosts it.
- Memory sync method + interval (snapshot pull vs log ship).
- Failover rule: DNS/tailnet name flip vs agents retry second URL.
