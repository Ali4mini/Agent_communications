#!/usr/bin/env python3
"""Porch: the only public door (pivot Nov 15). TLS HTTPS relay on :8443.
Agents without Tailnet POST here with their NATS login; porch validates
(lane == from, session shape, to allowlist), publishes into the tailnet-only
NATS lane hermes.inbox.<from>, waits for the bridge reply on
agents.<from>.inbox (same session), and returns it. Core :4222 never opens.
Stdlib only. Secrets never logged."""
import base64, hashlib, json, os, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
import ssl

BASE = os.path.dirname(os.path.abspath(__file__))
NATS_URL = os.environ.get("NATS_URL", "")
CERT = os.path.join(BASE, "porch.crt")
KEY = os.path.join(BASE, "porch.key")
PORT = int(os.environ.get("PORCH_PORT", "8443"))
REPLY_TIMEOUT = int(os.environ.get("PORCH_REPLY_TIMEOUT", "130"))

VALID_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
VALID_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PROFILES = set("agents_manager binux_mgmt career config_selling_bot confiigchi_content divar finance infra_ops iran_reach_probe komak_moshaver meshcat_erp mysteryplay_new seo shopping speed_service talacrm vpn_bot vpn_outreach vpnspeed_content".split())

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

class H(BaseHTTPRequestHandler):
    server_version = "porch/1"
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
        p = urlparse(self.path).path
        if p == "/health":
            return self._send(200, {"ok": True, "now": time.strftime("%FT%TZ", time.gmtime())})
        if p == "/fingerprint":
            try:
                der = ssl.PEM_cert_to_DER_cert(open(CERT, encoding="utf-8").read())
                fp = hashlib.sha256(der).hexdigest().upper()
                return self._send(200, {"sha256": ":".join(fp[i:i+2] for i in range(0, len(fp), 2))})
            except Exception as e:
                return self._send(500, {"error": "no cert"})
        self.send_response(404); self.end_headers()
    def do_POST(self):
        if urlparse(self.path).path != "/submit":
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
        try:
            ln = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            ln = 0
        if ln <= 0 or ln > 12000:
            return self._send(400, {"type": "error", "body": "bad length"})
        try:
            m = json.loads(self.rfile.read(ln).decode())
        except Exception:
            return self._send(400, {"type": "error", "body": "bad json"})
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
                    return self._send(200, rep)
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
    srv = HTTPServer(("0.0.0.0", PORT), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print("porch on :%d (reply-wait %ss)" % (PORT, REPLY_TIMEOUT), flush=True)
    srv.serve_forever()
