#!/usr/bin/env python3
"""Porch: the only public door (pivot Nov 15). TLS HTTPS relay on :9443.
Agents without Tailnet POST here with their NATS login; porch validates
(lane == from, session shape, to allowlist), publishes into the lane
hermes.inbox.<from>, waits for the bridge reply on agents.<from>.inbox
(same session), and returns it. Core :4222 never opens.

Mailbox (Nov 15, Alireza-approved): porch also holds durable subs on each
spool agent's agents.<name>.inbox (+ attempts agents.broadcast, currently
fence-denied server-side so broadcast arrives as per-agent inbox copies)
and spools envelopes to JSONL per agent (24h expiry, Q25). Sleepers poll
GET /inbox?since=<cursor> + POST /inbox/ack. POST /heartbeat records
presence (NATS publish where fences allow, else direct presence-file write
so the bridge sees it either way).

Webhook wake (Nov 15, Alireza-approved): every spool append fires a
debounced HTTPS notify to the agent's webhook (config in
/home/dev/.secrets/grokbot-webhook.env, re-read per notify; missing or
placeholder values = quietly off). No body content, no secrets in notifies.
Stdlib only. Secrets never logged."""
import base64, hashlib, json, os, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import ssl
import urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
NATS_URL = os.environ.get("NATS_URL", "")
CERT = os.path.join(BASE, "porch.crt")
KEY = os.path.join(BASE, "porch.key")
PORT = int(os.environ.get("PORCH_PORT", "9443"))
REPLY_TIMEOUT = int(os.environ.get("PORCH_REPLY_TIMEOUT", "130"))
MAILBOX_DIR = os.environ.get("PORCH_MAILBOX_DIR", "/home/dev/.porch-mailbox")
BRIDGE_PRESENCE_DIR = os.environ.get(
    "BRIDGE_PRESENCE_DIR",
    "/home/dev/.hermes/profiles/agents_manager/nats-bridge/presence")
HOLD_SECS = 86400  # 24h spool expiry (Q25)
WEBHOOK_ENV_FILE = "/home/dev/.secrets/grokbot-webhook.env"
WEBHOOK_DEBOUNCE = 20  # max 1 notify per 20s per recipient
WEBHOOK_TIMEOUT = 10  # seconds per attempt
WEBHOOK_RETRIES = (0, 2, 8)  # backoff sleeps before attempts 1..3

VALID_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
VALID_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VALID_STATUS = {"alive", "busy", "free", "away"}
PROFILES = set("agents_manager agent_communications binux_mgmt career config_selling_bot confiigchi_content divar finance infra_ops iran_reach_probe meshcat_erp mysteryplay_new seo shopping speed_service talacrm vpn_bot vpn_outreach vpnspeed_content".split())
SPOOL_AGENTS = [a for a in os.environ.get("PORCH_SPOOL_AGENTS", "grokbot").split(",")
                if a and VALID_NAME.match(a)]

def load_users():
    """user -> password from NATS_URL userinfo in each env file."""
    users = {}
    d = "/home/dev/.secrets"
    try:
        files = [f for f in os.listdir(d) if f.startswith("nats-") and f.endswith(".env")]
    except OSError:
        return users
    for fn in files:
        try:
            txt = open(os.path.join(d, fn), encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"NATS_URL=\S*://([^:/@]+):([^@]+)@", txt)
        if m:
            users[m.group(1)] = m.group(2)
    return users

USERS = load_users()
HITS = {}  # ip -> [timestamps] for rate limiting
HITS_LOCK = threading.Lock()
_SEQ = 0
_SEQ_LOCK = threading.Lock()
SUBMIT_ACTIVE = set()  # (from, session) with a /submit wait in flight
SUBMIT_DONE = {}  # (from, session) -> ts of 200 reply already returned
SUB_LOCK = threading.Lock()
PENDING = {}  # agent -> [notify items] awaiting debounce window
NOTIFY_LAST = {}  # agent -> ts of last notify attempt
NOTIFY_LOCK = threading.Lock()
NOTIFY_EV = threading.Event()
_WEBHOOK_SKIP_LOGGED = False

def rate_ok(ip):
    now = time.time()
    with HITS_LOCK:
        lst = [t for t in HITS.get(ip, []) if now - t < 60]
        if len(lst) >= 30:
            HITS[ip] = lst
            return False
        lst.append(now)
        HITS[ip] = lst
        return True

def run_nats(args, url="", **kw):
    env = dict(os.environ)
    if url:
        env["NATS_URL"] = url
    elif NATS_URL:
        env["NATS_URL"] = NATS_URL
    return subprocess.run(["nats", "--server", env.get("NATS_URL", ""), *args],
                          capture_output=True, text=True, timeout=kw.get("timeout", 140), env=env)

def user_nats_url(user):
    pw = USERS.get(user, "")
    host = "100.124.214.63:4222"
    if NATS_URL and "@" in NATS_URL:
        host = NATS_URL.split("@", 1)[1].rstrip("/")
    from urllib.parse import quote
    return "nats://%s:%s@%s" % (user, quote(pw, safe=""), host)

def submit_mark_active(frm, sess):
    with SUB_LOCK:
        SUBMIT_ACTIVE.add((frm, sess))

def submit_mark_done(frm, sess):
    now = time.time()
    with SUB_LOCK:
        SUBMIT_ACTIVE.discard((frm, sess))
        SUBMIT_DONE[(frm, sess)] = now
        for k, ts in list(SUBMIT_DONE.items()):
            if now - ts > 3600:
                SUBMIT_DONE.pop(k, None)

def submit_mark_end(frm, sess):
    with SUB_LOCK:
        SUBMIT_ACTIVE.discard((frm, sess))

# ---- webhook wake ----
def _is_placeholder(v):
    return (not v) or ("REPLACE" in v) or ("EXAMPLE" in v)

def webhook_conf():
    """Re-read per notify so filling the file later needs no restart."""
    path = os.environ.get("GROKBOT_WEBHOOK_ENV_FILE", WEBHOOK_ENV_FILE)
    conf = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k in ("GROKBOT_WEBHOOK_URL", "GROKBOT_WEBHOOK_KEY",
                         "GROKBOT_WEBHOOK_KEY_HEADER"):
                    conf[k] = v.strip().strip("'\"")
    except OSError:
        return {}
    url, key = conf.get("GROKBOT_WEBHOOK_URL", ""), conf.get("GROKBOT_WEBHOOK_KEY", "")
    if _is_placeholder(url) or _is_placeholder(key):
        return {}
    if url.startswith("http://"):
        host = url.split("/")[2].split("@")[-1].split(":")[0].lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            return {}  # real webhooks must be https
    elif not url.startswith("https://"):
        return {}
    return conf

def should_fire(agent, env):
    """No notify for replies the agent already got via its own /submit."""
    try:
        if not isinstance(env, dict):
            return False
        if env.get("redelivered") is True:
            return True  # held-reply re-delivery: always new mail
        t = env.get("type", "")
        if t == "message":
            return True  # direct tasks + broadcast copies
        if t in ("reply", "error"):
            key = (env.get("to", agent), env.get("session", ""))
            with SUB_LOCK:
                if key in SUBMIT_ACTIVE:
                    return False
                ts = SUBMIT_DONE.get(key, 0)
            if ts and time.time() - ts < 600:
                return False
            return True  # late reply after a 504 / no active wait
        return True
    except Exception:
        return False

def notify_enqueue(agent, env):
    try:
        if not should_fire(agent, env):
            return
        item = {"session": env.get("session", ""), "from": env.get("from", ""),
                "type": env.get("type", "")}
        with NOTIFY_LOCK:
            PENDING.setdefault(agent, []).append(item)
        NOTIFY_EV.set()
    except Exception:
        pass  # never break mail delivery

def webhook_post(url, headers, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={**headers, "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return "error"

def notifier():
    global _WEBHOOK_SKIP_LOGGED
    while True:
        NOTIFY_EV.wait(timeout=5)
        NOTIFY_EV.clear()
        now = time.time()
        with NOTIFY_LOCK:
            due = {}
            for agent, items in list(PENDING.items()):
                if not items:
                    PENDING.pop(agent, None)
                    continue
                if now - NOTIFY_LAST.get(agent, 0) >= WEBHOOK_DEBOUNCE:
                    due[agent] = items
                    PENDING[agent] = []
        for agent, items in due.items():
            uniq, seen = [], set()
            for it in items:
                if it["session"] not in seen:
                    seen.add(it["session"])
                    uniq.append(it)
            latest = uniq[-1]
            payload = {"event": "mail", "to": agent, "session": latest["session"],
                       "from": latest["from"], "type": latest["type"],
                       "ts": time.strftime("%FT%TZ", time.gmtime())}
            if len(uniq) > 1:
                payload["sessions"] = [u["session"] for u in uniq]
                payload["count"] = len(uniq)
            conf = webhook_conf()
            if not conf:
                if not _WEBHOOK_SKIP_LOGGED:
                    print("webhook: not configured, notifications off", flush=True)
                    _WEBHOOK_SKIP_LOGGED = True
                NOTIFY_LAST[agent] = now
                continue
            _WEBHOOK_SKIP_LOGGED = False
            hname = conf.get("GROKBOT_WEBHOOK_KEY_HEADER", "Authorization") or "Authorization"
            key = conf["GROKBOT_WEBHOOK_KEY"]
            hval = "Bearer " + key if hname.lower() == "authorization" else key
            status = "error"
            for backoff in WEBHOOK_RETRIES:
                if backoff:
                    time.sleep(backoff)
                status = webhook_post(conf["GROKBOT_WEBHOOK_URL"], {hname: hval}, payload)
                if isinstance(status, int) and 200 <= status < 300:
                    break
            # status code only — never URL query, never key
            print("webhook to=%s count=%d status=%s" % (agent, len(uniq), status), flush=True)
            NOTIFY_LAST[agent] = time.time()

# ---- mailbox spool ----
def _paths(agent):
    base = os.path.join(MAILBOX_DIR, agent)
    return base + ".jsonl", base + ".ack", base + ".poll"

def new_cursor():
    global _SEQ
    with _SEQ_LOCK:
        _SEQ = (_SEQ + 1) % 1000000
        n = _SEQ
    ms = int(time.time() * 1000)
    return "%013d-%05d-%06d" % (ms, os.getpid() % 100000, n)

def spool_save(agent, subj, env):
    try:
        os.makedirs(MAILBOX_DIR, mode=0o700, exist_ok=True)
        jl, _, _ = _paths(agent)
        line = json.dumps({"cursor": new_cursor(), "ts": int(time.time()),
                           "subj": subj, "env": env})
        with open(jl, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        try:
            os.chmod(jl, 0o600)
        except OSError:
            pass
        if os.path.getsize(jl) > 2000000:
            spool_prune(agent)
        notify_enqueue(agent, env)
    except OSError:
        pass

def spool_prune(agent):
    jl, _, _ = _paths(agent)
    try:
        cutoff = int(time.time()) - HOLD_SECS
        with open(jl, encoding="utf-8") as f:
            rows = f.readlines()
        kept = []
        for r in rows:
            try:
                d = json.loads(r)
                if d.get("ts", 0) >= cutoff and d.get("cursor"):
                    kept.append(r if r.endswith("\n") else r + "\n")
            except Exception:
                continue
        with open(jl, "w", encoding="utf-8") as f:
            f.writelines(kept)
    except OSError:
        pass

def spool_read(agent, since):
    jl, ackp, _ = _paths(agent)
    if not since:
        try:
            since = open(ackp, encoding="utf-8").read().strip()
        except OSError:
            since = ""
    msgs, last = [], (since or "0")
    try:
        cutoff = int(time.time()) - HOLD_SECS
        with open(jl, encoding="utf-8") as f:
            for r in f:
                try:
                    d = json.loads(r)
                except Exception:
                    continue
                if d.get("ts", 0) < cutoff or not d.get("cursor"):
                    continue
                if since and d["cursor"] <= since:
                    continue
                msgs.append(d["env"])
                last = d["cursor"]
                if len(msgs) >= 200:
                    break
    except OSError:
        pass
    return msgs, last

def spool_ack(agent, cursor):
    _, ackp, _ = _paths(agent)
    try:
        prev = open(ackp, encoding="utf-8").read().strip()
    except OSError:
        prev = ""
    if cursor and cursor > prev:
        try:
            with open(ackp, "w", encoding="utf-8") as f:
                f.write(cursor + "\n")
            os.chmod(ackp, 0o600)
        except OSError:
            pass
        return cursor
    return prev

def touch_poll(agent):
    _, _, pollp = _paths(agent)
    try:
        with open(pollp, "w", encoding="utf-8") as f:
            f.write("%d\n" % int(time.time()))
        os.chmod(pollp, 0o600)
    except OSError:
        pass

def spool_worker(agent, subj, url):
    """Durable sub; every envelope on subj lands in the agent spool."""
    while True:
        try:
            p = subprocess.Popen(["nats", "--server", url, "sub", "--raw", subj],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, bufsize=1)
            for raw in (p.stdout or []):
                line = raw.strip()
                if not line.startswith("{"):
                    continue
                try:
                    env = json.loads(line)
                except Exception:
                    continue
                if not isinstance(env, dict) or not env.get("session"):
                    continue
                spool_save(agent, subj, env)
            try:
                p.wait(timeout=5)
            except Exception:
                pass
        except Exception:
            pass
        # broadcast is fence-denied today: slow retry so it self-heals if
        # server permissions ever allow it; inbox uses the fast retry.
        time.sleep(60 if subj == "agents.broadcast" else 5)

def start_spoolers():
    try:
        os.makedirs(MAILBOX_DIR, mode=0o700, exist_ok=True)
    except OSError:
        pass
    for agent in SPOOL_AGENTS:
        if agent not in USERS:
            continue
        t = threading.Thread(target=spool_worker,
                             args=(agent, "agents.%s.inbox" % agent, user_nats_url(agent)),
                             daemon=True)
        t.start()
    # broadcast fan-out copy per spool agent (subject currently fence-denied;
    # worker retries so it starts working if fences ever allow it)
    for agent in SPOOL_AGENTS:
        t = threading.Thread(target=spool_worker,
                             args=(agent, "agents.broadcast", NATS_URL),
                             daemon=True)
        t.start()
    threading.Thread(target=notifier, daemon=True).start()
    # periodic expiry prune
    def pruner():
        while True:
            time.sleep(3600)
            for agent in SPOOL_AGENTS:
                spool_prune(agent)
    threading.Thread(target=pruner, daemon=True).start()

class H(BaseHTTPRequestHandler):
    server_version = "porch/3"
    def log_message(self, *a):
        pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def _auth(self):
        a = self.headers.get("Authorization", "")
        if not a.startswith("Basic "):
            return None
        try:
            raw = base64.b64decode(a[6:]).decode()
        except Exception:
            return None
        u, _, p = raw.partition(":")
        if USERS.get(u) == p and VALID_NAME.match(u):
            return u
        return None
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._send(200, {"ok": True, "now": time.strftime("%FT%TZ", time.gmtime())})
        if u.path == "/fingerprint":
            try:
                der = ssl.PEM_cert_to_DER_cert(open(CERT, encoding="utf-8").read())
                fp = hashlib.sha256(der).hexdigest().upper()
                return self._send(200, {"sha256": ":".join(fp[i:i+2] for i in range(0, len(fp), 2))})
            except Exception:
                return self._send(500, {"error": "no cert"})
        if u.path == "/inbox":
            user = self._auth()
            if not user:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="porch"')
                self.end_headers()
                return
            if user not in SPOOL_AGENTS:
                return self._send(404, {"type": "error", "body": "no mailbox for " + user})
            if not rate_ok(self.client_address[0]):
                return self._send(429, {"type": "error", "body": "rate limited, retry in a minute"})
            qs = parse_qs(u.query)
            since = (qs.get("since") or [""])[0]
            msgs, cursor = spool_read(user, since)
            touch_poll(user)
            return self._send(200, {"messages": msgs, "cursor": cursor})
        self.send_response(404); self.end_headers()
    def _read_json(self, limit=12000):
        try:
            ln = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            ln = 0
        if ln <= 0 or ln > limit:
            return None, "bad length"
        try:
            return json.loads(self.rfile.read(ln).decode()), ""
        except Exception:
            return None, "bad json"
    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/submit", "/inbox/ack", "/heartbeat"):
            self.send_response(404); self.end_headers(); return
        ip = self.client_address[0]
        if not rate_ok(ip):
            return self._send(429, {"type": "error", "body": "rate limited, retry in a minute"})
        user = self._auth()
        if not user:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="porch"')
            self.end_headers()
            return
        if path == "/inbox/ack":
            m, err = self._read_json()
            if m is None:
                return self._send(400, {"type": "error", "body": err})
            if m.get("from") != user or not VALID_NAME.match(m.get("from", "")):
                return self._send(403, {"type": "error",
                                        "body": "identity mismatch: ack from must equal login"})
            cur = spool_ack(user, m.get("cursor", ""))
            touch_poll(user)
            return self._send(200, {"ok": True, "cursor": cur})
        if path == "/heartbeat":
            m, err = self._read_json()
            if m is None:
                return self._send(400, {"type": "error", "body": err})
            frm = m.get("from", "")
            if frm != user or not VALID_NAME.match(frm):
                return self._send(403, {"type": "error",
                                        "body": "identity mismatch: auth %s != from %s" % (user, frm)})
            status = m.get("status", "")
            if status not in VALID_STATUS:
                return self._send(400, {"type": "error", "body": "bad status"})
            caps = m.get("caps", [])
            if not isinstance(caps, list):
                return self._send(400, {"type": "error", "body": "bad caps"})
            now = int(time.time())
            hb = {"from": frm, "status": status, "caps": caps,
                  "ts": m.get("ts", now), "at": now, "wake": m.get("wake", "")}
            via = "presence-file"
            r = run_nats(["pub", "agents.%s.heartbeat" % frm, json.dumps(hb)],
                         url=user_nats_url(frm), timeout=10)
            if r.returncode == 0:
                via = "nats"
            else:
                # fences deny heartbeat publish today: write the bridge
                # presence file directly (same host, same format) so the
                # bridge sees the heartbeat either way.
                try:
                    os.makedirs(BRIDGE_PRESENCE_DIR, mode=0o700, exist_ok=True)
                    p = os.path.join(BRIDGE_PRESENCE_DIR, frm)
                    with open(p, "w", encoding="utf-8") as f:
                        f.write("%d %s\n" % (now, json.dumps(hb)))
                    os.chmod(p, 0o600)
                except OSError:
                    return self._send(500, {"type": "error", "body": "heartbeat store failed"})
            return self._send(200, {"ok": True, "from": frm, "status": status,
                                   "at": now, "via": via})
        # /submit (unchanged relay)
        m, err = self._read_json()
        if m is None:
            return self._send(400, {"type": "error", "body": err})
        frm, to = m.get("from", ""), m.get("to", "hermes")
        sess, body = m.get("session", ""), m.get("body", "")
        if frm != user or not VALID_NAME.match(frm):
            return self._send(403, {"type": "error", "body": "identity mismatch: auth %s != from %s" % (user, frm)})
        if not VALID_SESSION.match(sess or ""):
            return self._send(400, {"type": "error", "body": "bad session"})
        if not body or not VALID_NAME.match(to or ""):
            return self._send(400, {"type": "error", "body": "bad to/body"})
        if to != "hermes" and to not in PROFILES:
            return self._send(200, {"from": "hermes", "to": frm, "session": sess, "type": "error", "body": "unknown recipient: " + to})
        lane = "hermes.inbox." + frm
        pub = json.dumps({"from": frm, "to": to, "session": sess, "type": "message", "body": body})
        uurl = user_nats_url(frm)
        r = run_nats(["pub", lane, pub], url=uurl, timeout=20)
        if r.returncode != 0:
            return self._send(502, {"type": "error", "body": "lane publish failed"})
        # wait for the bridge reply on the agent's own inbox
        submit_mark_active(frm, sess)
        try:
            deadline = time.time() + REPLY_TIMEOUT
            while time.time() < deadline:
                left = max(1, int(deadline - time.time()))
                try:
                    r = run_nats(["sub", "--count=1", "agents.%s.inbox" % frm], url=uurl, timeout=min(left, 60) + 5)
                except Exception:
                    continue
                for line in (r.stdout or "").splitlines():
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        rep = json.loads(line)
                    except Exception:
                        continue
                    if rep.get("session") == sess and rep.get("from") == "hermes":
                        submit_mark_done(frm, sess)
                        return self._send(200, rep)
        finally:
            submit_mark_end(frm, sess)
        return self._send(504, {"from": "hermes", "to": frm, "session": sess, "type": "error", "body": "reply timeout — held, retry same session later"})

if __name__ == "__main__":
    if not os.path.exists(CERT) or not os.path.exists(KEY):
        print("missing cert/key: run gen-cert.sh first", flush=True)
        sys.exit(1)
    if not NATS_URL:
        # fall back to bridge hermes creds for the NATS side
        try:
            txt = open("/home/dev/.secrets/nats-hermes.env", encoding="utf-8").read()
            m = re.search(r"NATS_URL=(\S+)", txt)
            if m:
                NATS_URL = m.group(1).strip()
        except OSError:
            pass
    start_spoolers()
    srv = HTTPServer(("0.0.0.0", PORT), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print("porch on :%d (reply-wait %ss, spool=%s)" % (PORT, REPLY_TIMEOUT, ",".join(SPOOL_AGENTS) or "none"), flush=True)
    srv.serve_forever()
