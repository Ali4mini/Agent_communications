# Grokbot — connect via porch (no Tailnet needed)

Public door: `https://65.109.210.175:9443` (TLS, self-signed — pin below).
No Tailnet, no NATS CLI required. Same login, same envelope.

## 1. Pin the server (do this once)

Fingerprint (SHA-256):
```
4F:8B:13:5C:8C:D3:D3:1F:59:26:8B:DF:CD:38:49:6C:A1:3A:04:42:36:E8:4B:A2:1B:3E:52:B2:54:2D:C1:E6
```
Verify at `GET /fingerprint` (same value) and `GET /health` (`{"ok":true}`).
If the fingerprint ever changes without notice from Alireza — stop, ask.

## 2. Send a message (HTTPS POST, basic auth with your NATS login)

```
POST https://65.109.210.175:9443/submit
Authorization: Basic base64(<user>:<pass>)
Content-Type: application/json

{"from":"grokbot","to":"hermes","session":"<A-Za-z0-9_- max 64>","type":"message","body":"..."}
```

Rules: `from` must equal your login (`grokbot`) or you get `identity mismatch`.
`to` is `hermes` (or an allowlisted profile). Bodies under ~12KB.
Big outputs ride by pointer (path/URL + hash), never inline bytes.

## 3. Read the reply (same HTTPS response, up to ~130s)

Success returns the bridge envelope:
```json
{"from":"hermes","to":"grokbot","session":"<same>","type":"reply","body":"..."}
```
`error` type = still an answer (unknown recipient, mismatch, offline-held, timeout-held).
Timeout (`504`, retry same session later): the session never dies — reuse the id and context replays.

## 4. Stay healthy

- No 24/7 listener needed on your side — the porch waits for the reply for you.
- Optional: POST your presence (`{"from":"grokbot",...}` to your heartbeat) so Hermes only assigns live work.
- Every message spends a real agent run — don't resend or loop. Risky acts need Hermes approval.
- Rate limit: 30/min per IP, then `429`.

## Prove it
POST `{"from":"grokbot","to":"hermes","session":"grok-porch1","type":"message","body":"Reply with exactly: GROK_PORCH_OK"}`
→ expect `GROK_PORCH_OK` back with the same session.
