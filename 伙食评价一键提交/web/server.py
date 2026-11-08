#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — 伙食评价网页版（带登录、HTTPS、限流）

安全设计（允许被局域网内其他设备访问）:
  1. 强制登录：--password 设的密码，登录后发 HttpOnly+SameSite Cookie 会话
  2. HTTPS：--tls-cert/--tls-key 指定证书；--self-signed 自动生成一张
  3. 登录限流：同一 IP 连续失败 5 次锁 10 分钟，防爆破
  4. IP 白名单（可选）：--allow-ip 1.2.3.4,5.6.7.8
  5. 安全响应头：HSTS / nosniff / DENY frame / no-referrer / CSP
  6. 监听 0.0.0.0 又没设密码 → 直接拒绝启动（除非显式 --allow-insecure）

启动:
  # 本机自用（不用密码）
  python web/server.py

  # 局域网 + 自签证书（一般用不到，反代或本机访问即可）
  python web/server.py --host 0.0.0.0 --port 8443 --password '强密码' --self-signed

  # 有域名和证书（推荐，浏览器不报警）
  python web/server.py --host 127.0.0.1 --port 8443 --password '强密码' \
      --tls-cert /path/fullchain.pem --tls-key /path/privkey.pem --trust-proxy
"""
import argparse, base64, hashlib, hmac, json, os, queue, random, re, secrets, ssl, struct, sys, threading, datetime, time, traceback
from urllib.parse import quote
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import hqhs_eval as hq            # noqa: E402
import import_accounts as _acct    # noqa: E402  （别叫 imp，会顶掉标准库）

CONFIG = os.path.join(ROOT, "eval_config.json")
OUT_DIR = os.path.join(ROOT, "out")          # 正常情况：挂载出来的 ./data
LEDGER = os.path.join(OUT_DIR, "submitted.json")
INDEX = os.path.join(HERE, "index.html")
VERSION = "5.7.4"
START_TIME = time.time()


def code_mtime():
    """核心代码最后修改时间。比进程启动还新，说明改了文件没重启。"""
    paths = [os.path.abspath(__file__), os.path.abspath(hq.__file__)]
    pure = os.path.join(os.path.dirname(os.path.abspath(hq.__file__)), "aes_pure.py")
    paths.append(pure)
    m = 0.0
    for p in paths:
        try:
            m = max(m, os.path.getmtime(p))
        except OSError:
            pass
    return m

# ---- 安全状态 ----
PASSWORD = None
TOTP_SECRET = None       # Base32 密钥，配了就启用动态码登录
TOTP_WINDOW = 1          # 允许前后各偏 1 个时间窗（±30 秒），容忍手机时钟误差
TOTP_USED = {}           # 已用过的验证码 {counter: 用掉的时间}，防重放
AUTH_MODE = "password"   # password | totp | both —— 配了动态码密钥默认只认动态码
SALT = b"hqhs-web-salt-v1"
SESSIONS = {}
FAILS = defaultdict(list)
ALLOW_IPS = None
TRUST_PROXY = False
IS_TLS = False
IS_SELF_SIGNED = False
NO_HSTS = False
SESSION_HOURS = 12
MAX_FAILS, FAIL_WINDOW, LOCK_SECONDS = 5, 600, 600
_LOGIN_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()
LAST_ERROR = {"trace": "", "at": ""}


def _gc_loop():
    """每 10 分钟清一次过期会话和过老的失败记录"""
    while True:
        time.sleep(600)
        now = time.time()
        with _LOGIN_LOCK:
            for tok in [t for t, v in list(SESSIONS.items()) if v.get("exp", 0) < now]:
                SESSIONS.pop(tok, None)
            for ip in list(FAILS.keys()):
                arr = [t for t in FAILS[ip] if now - t < FAIL_WINDOW]
                if arr:
                    FAILS[ip] = arr
                else:
                    FAILS.pop(ip, None)


def today():
    return datetime.date.today().isoformat()


def now_str():
    return datetime.datetime.now().strftime("%H:%M:%S")


def totp_code(secret, counter, digits=6):
    """按 RFC 6238 算一个 6 位动态码。secret 是 Base32（Authenticator 那种格式）。"""
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    off = h[-1] & 0x0F
    num = struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF
    return str(num % (10 ** digits)).zfill(digits)


def totp_now(secret, offset=0, step=30):
    return totp_code(secret, int(time.time()) // step + offset)


def verify_totp(code):
    """校验动态码。返回 True/False。同一个码只能用一次。"""
    if not TOTP_SECRET:
        return False
    code = re.sub(r"\s+", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", code):
        return False
    base = int(time.time()) // 30
    # 清掉两分钟前的记录，别让字典无限涨
    for c in [k for k, t in TOTP_USED.items() if time.time() - t > 120]:
        TOTP_USED.pop(c, None)
    for off in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        counter = base + off
        if hmac.compare_digest(totp_code(TOTP_SECRET, counter), code):
            if counter in TOTP_USED:
                return False          # 这个码刚被用过，防重放
            TOTP_USED[counter] = time.time()
            return True
    return False


def gen_totp_secret():
    """生成一个新的 Base32 密钥（160 bit，标准长度）。"""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def otpauth_url(secret, label="hqhs-eval", issuer="hqhs-eval"):
    return (f"otpauth://totp/{quote(issuer)}:{quote(label)}"
            f"?secret={secret}&issuer={quote(issuer)}&period=30&digits=6")


def pw_hash(p):
    return hashlib.pbkdf2_hmac("sha256", p.encode(), SALT, 120_000).hex()


def load_cfg():
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cfg(cfg):
    """写回 eval_config.json，返回有没有真的落到磁盘。

    两种写法都要试：
      ① 先写临时文件再 rename —— 普通文件这样最安全（不会写一半崩掉）
      ② 失败就原地覆盖 —— 容器里 eval_config.json 是单文件 bind mount，
         挂载点不允许 rename（会报 Device or resource busy / Permission denied），
         哪怕目录 777 也一样。这时候只能直接往原文件里写。

    写不成不算致命错误：前端把地址存在浏览器里，功能照样能用，
    只是换台电脑要重填。
    """
    data = json.dumps(cfg, ensure_ascii=False, indent=2)
    tmp = CONFIG + ".tmp"

    # ① 原子替换（普通文件）
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, CONFIG)
        return True
    except OSError:
        pass

    # ② 原地覆盖（bind mount 的单文件挂载点）
    try:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        with open(CONFIG, "w", encoding="utf-8") as f:
            f.write(data)
        return True
    except OSError:
        return False


def cfg_writable():
    """配置文件能不能写。用 r+ 探测 —— 和实际保存走同一条路，
    别用 open(..., 'a') 骗自己（追加能成功，rename 却不行）。"""
    try:
        with open(CONFIG, "r+", encoding="utf-8"):
            return True
    except OSError:
        return False


def _presets(cfg):
    """常用服务器地址：配置里的 presets + 当前 host，去重后给前端做「一键填入」"""
    out = []
    for x in (cfg.get("presets") or []):
        x = str(x).strip()
        if x and x not in out:
            out.append(x)
    h = str(cfg.get("host") or "").strip()
    if host_ok(h) and h not in out:
        out.insert(0, h)
    return out[:6]


def host_ok(h):
    v = str(h or "").strip()
    return bool(v) and not v.startswith("[") and "填" not in v


# ---------------- 台账 ----------------
_ledger_lock = threading.Lock()


def resolve_out_dir():
    """挑一个能写的输出目录。

    容器里 /app/out 是挂载点，宿主机上的 ./data 属主要是和容器内 uid（1000）
    对不上，日志和台账就都写不进去（Permission denied）。
    这时候退到容器内的 /app/.local-out —— 至少当天不会重复提交，
    虽然容器重建会丢，但比整个流程失败好。
    """
    for d in (OUT_DIR, os.path.join(ROOT, ".local-out")):
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".wtest")
            with open(probe, "w"):
                pass
            os.remove(probe)
            return d
        except OSError:
            continue
    return OUT_DIR


def load_ledger():
    if not os.path.exists(LEDGER):
        return {}
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ledger_mark(user):
    """记台账。写不进去只警告 —— 不能让「已经提交成功」被记成失败。"""
    with _ledger_lock:
        try:
            lg = load_ledger()
            lg.setdefault(today(), {})[user] = now_str()
            keep = sorted(lg.keys())[-30:]
            lg = {k: lg[k] for k in keep}
            os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
            tmp = LEDGER + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(lg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, LEDGER)
            return True
        except OSError as e:
            print(f"[警告] 台账写不进去（{e}）：{user} 已提交，但这次没记进去，"
                  f"同一天再跑可能会重复提交。检查 {os.path.dirname(LEDGER)} 权限", flush=True)
            return False


def ledger_today():
    return load_ledger().get(today(), {})


# ---------------- 名单解析 ----------------
def parse_text(text):
    rows, bad = [], []
    for i, line in enumerate((text or "").splitlines(), 1):
        if not line.strip():
            continue
        m = _acct.parse_line(line)
        if m and m.get("userName") and m.get("passWord"):
            rows.append(m)
        else:
            bad.append({"line": i, "text": line.strip()[:60]})
    seen, uniq = set(), []
    for r in rows:
        if r["userName"] in seen:
            continue
        seen.add(r["userName"])
        uniq.append(r)
    return uniq, bad


# ---------------- 单个账号 ----------------
def process_one(acc, cfg, dry, force, done_today):
    name = (acc.get("name") or acc.get("userName") or "").strip()
    user = str(acc.get("userName") or "").strip()
    pwd = str(acc.get("passWord") or "")
    res = {"name": name, "userName": user, "status": "FAIL", "msg": "", "dept": "", "q": 0}

    if not user or not pwd:
        res["msg"] = "缺账号或密码"
        return res
    if not force and user in done_today:
        res["status"] = "SKIP"
        res["msg"] = f"今天 {done_today[user]} 已交过，跳过"
        return res

    try:
        c = hq.Client(cfg["host"], timeout=cfg.get("timeout", 15), scheme=cfg.get("scheme", "http"))
        c.ensure_scheme()
        hq.login(c, user, pwd)
        res["dept"] = (c.user or {}).get("dept_name") or ""

        grade = cfg.get("grade") or (c.user or {}).get("orgGrade") or ""
        detail = hq.get_detail(c, cfg.get("saveId", ""), grade)
        sat = detail.get("satisfiedList") or []
        sup = detail.get("superviseList") or []
        res["q"] = len(sat) + len(sup)
        if not sat and not sup:
            res["status"] = "SKIP"
            res["msg"] = "服务端没下发任务（今天已交 / 不在时间窗）"
            return res

        hq.fill_and_save(c, detail, strategy=cfg.get("strategy", "max"),
                         dry_run=dry, verbose=False)
        if not dry:
            ledger_mark(user)
        res["status"] = "OK"
        res["msg"] = ("预演通过" if dry else "提交成功") + f"（{len(sat)}+{len(sup)} 题）"
        return res

    except hq.ApiError as e:
        if e.is_daily_limit:
            res["status"] = "SKIP"
            res["msg"] = "当天次数已达上限（视为已交）"
        else:
            res["msg"] = str(e)
        return res
    except Exception as e:
        tb = traceback.format_exc()
        LAST_ERROR["trace"] = tb
        LAST_ERROR["at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hq.log(f"[错误] {user}: {type(e).__name__}: {e}\n{tb}")
        raw = str(e)
        msg = raw
        if "用户名或密码错误" in raw or "用户名不存在" in raw or ("密码" in raw and "错误" in raw):
            msg = "账号或密码错误"
        elif "Token" in raw:
            msg = "登录态异常"
        elif "Max retries" in raw or "timed out" in raw or "Connection" in raw:
            msg = "连不上服务器（机房内网？地址对吗？）"
        else:
            # 查不出来的怪错误：带上异常类型 + 出错位置，方便一眼定位
            tb = traceback.extract_tb(e.__traceback__)
            where = ""
            if tb:
                f = tb[-1]
                where = f"  @{os.path.basename(f.filename)}:{f.lineno}"
            msg = f"{type(e).__name__}: {raw}{where}"
        res["msg"] = msg
        return res


# ---------------- 自签证书 ----------------
def make_self_signed(cert_path, key_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import ipaddress

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hqhs-eval")])
    now = datetime.datetime.utcnow()
    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(key, hashes.SHA256()))
    os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "hqhs-web/1.1"
    protocol_version = "HTTP/1.1"

    def _client_ip(self):
        if TRUST_PROXY:
            xff = self.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[0].strip()
        return self.client_address[0]

    def _security_headers(self):
        h = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; "
                                        "style-src 'self' 'unsafe-inline'; "
                                        "script-src 'self' 'unsafe-inline'; "
                                        "connect-src 'self'; frame-ancestors 'none'"),
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        }
        # 自签证书绝对不能发 HSTS：
        # 浏览器会记住「这个主机以后只能用 HTTPS」，有效期一年，
        # 之后再用 http:// 访问会被强制改成 https://，直接连不上 —— 而且用户很难自己清掉。
        if IS_TLS and not IS_SELF_SIGNED and not NO_HSTS:
            h["Strict-Transport-Security"] = "max-age=31536000"
        return h

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in self._security_headers().items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), extra=extra)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return {}
        if not n or n > 2_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _guard(self, fn):
        """兜住一切未捕获异常。
        以前异常会把连接直接掐断，浏览器只看到 "Failed to fetch"，
        根本不知道服务端已经炸了 —— 这是最坑的一种表现。"""
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            pass                      # 客户端自己断了，不管
        except Exception as e:
            tb = traceback.format_exc()
            LAST_ERROR["trace"] = tb
            LAST_ERROR["at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                hq.log(f"[服务端异常] {type(e).__name__}: {e}\n{tb}")
            except Exception:
                pass
            try:
                import re as _re
                hits = _re.findall(r'File "([^"]+)", line (\d+)', tb)
                where = f"{os.path.basename(hits[-1][0])}:{hits[-1][1]}" if hits else ""
                self._json({"error": f"服务端内部错误：{type(e).__name__}: {e}",
                            "where": where}, 500)
            except Exception:
                pass                  # 响应头都发过了，只能放弃

    def _ip_allowed(self):
        if ALLOW_IPS is None:
            return True
        return self._client_ip() in ALLOW_IPS

    def _cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid":
                return v
        return None

    def _session_ok(self):
        # 两种认证方式都要算进来 —— 只判断 PASSWORD 的话，
        # 「只用动态码」模式下所有接口都会无鉴权放行（这是个真 bug）
        if not PASSWORD and not TOTP_SECRET:
            return True
        tok = self._cookie_token()
        if not tok:
            return False
        s = SESSIONS.get(tok)
        if not s:
            return False
        if s["exp"] < time.time():
            SESSIONS.pop(tok, None)
            return False
        if s.get("ip") and s["ip"] != self._client_ip():
            return False
        return True

    def _lock_left(self):
        ip = self._client_ip()
        now = time.time()
        with _LOGIN_LOCK:
            arr = [t for t in FAILS[ip] if now - t < FAIL_WINDOW]
            FAILS[ip] = arr
            if len(arr) >= MAX_FAILS:
                return int(LOCK_SECONDS - (now - arr[0]))
        return 0

    def _note_fail(self):
        with _LOGIN_LOCK:
            FAILS[self._client_ip()].append(time.time())

    def _clear_fail(self):
        with _LOGIN_LOCK:
            FAILS.pop(self._client_ip(), None)

    def do_PUT(self):
        self._json({"error": "method not allowed"}, 405)

    def do_DELETE(self):
        self._json({"error": "method not allowed"}, 405)

    def log_message(self, *a):
        pass

    # ---- GET ----
    def do_GET(self):
        self._guard(self._do_GET)

    def _do_GET(self):
        if not self._ip_allowed():
            return self._json({"error": "forbidden"}, 403)
        u = urlparse(self.path)

        if u.path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(500, b"index.html missing", "text/plain")

        if u.path == "/api/state":
            cfg = load_cfg()
            host = cfg.get("host") or ""
            return self._json({
                "need_login": bool(PASSWORD or TOTP_SECRET),
                "auth_mode": AUTH_MODE,
                "totp_on": bool(TOTP_SECRET),
                "logged_in": self._session_ok(),
                "host": host if host_ok(host) else "",
                "presets": _presets(cfg),
                "need_host": not host_ok(host),
                "tls": IS_TLS,
                "version": VERSION,
                "stale": code_mtime() > START_TIME + 1,
                "aes_backend": hq.AES_BACKEND,
                "today": today(),
                "ledger_count": len(ledger_today()) if self._session_ok() else 0,
            })

        if u.path == "/api/config":
            if not self._session_ok():
                return self._json({"error": "未登录"}, 401)
            cfg = load_cfg()
            host = cfg.get("host") or ""
            return self._json({"host": host if host_ok(host) else "",
                               "need_host": not host_ok(host),
                               "strategy": cfg.get("strategy", "max"),
                               "today": today(), "ledger_count": len(ledger_today())})

        if u.path == "/api/ledger":
            if not self._session_ok():
                return self._json({"error": "未登录"}, 401)
            lg = ledger_today()
            return self._json({"date": today(), "count": len(lg), "users": lg})

        if u.path == "/api/diag":
            if not self._session_ok():
                return self._json({"error": "未登录"}, 401)
            rep = hq.env_report()
            rep["version"] = VERSION
            rep["stale"] = code_mtime() > START_TIME + 1
            cfg = load_cfg()
            rep["host"] = cfg.get("host") or ""
            rep["ledger_today"] = len(ledger_today())
            if host_ok(cfg.get("host")):
                try:
                    c = hq.Client(cfg["host"], timeout=8, scheme=cfg.get("scheme", "http"))
                    c.ensure_scheme()
                    r = c.s.get(c.base, timeout=8, allow_redirects=False)
                    rep["connect"] = f"OK  {c.base}  (HTTP {r.status_code})"
                except Exception as e:
                    rep["connect"] = f"失败  {type(e).__name__}: {e}"
                    rep["ok"] = False
                    rep.setdefault("problems", []).append("连不上服务器，检查内网连通性")
            else:
                rep["connect"] = "（还没填服务器地址）"
            rep["last_error"] = LAST_ERROR
            return self._json(rep)

        return self._json({"error": "not found"}, 404)

    def do_HEAD(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for k, v in self._security_headers().items():
                self.send_header(k, v)
            self.end_headers()
        except Exception:
            pass

    # ---- POST ----
    def do_POST(self):
        self._guard(self._do_POST)

    def _do_POST(self):
        if not self._ip_allowed():
            return self._json({"error": "forbidden"}, 403)
        u = urlparse(self.path)

        if u.path == "/api/login":
            left = self._lock_left()
            if left > 0:
                return self._json({"error": f"失败次数太多，请 {left // 60 + 1} 分钟后再试"}, 429)
            body = self._body()
            pw = str(body.get("password") or "")
            if not PASSWORD and not TOTP_SECRET:
                return self._json({"ok": True, "note": "未启用密码"})
            # AUTH_MODE 决定认哪种：totp 只认动态码，password 只认密码，both 都认
            ok_static = (AUTH_MODE in ("password", "both") and PASSWORD
                         and hmac.compare_digest(pw_hash(pw), PASSWORD))
            ok_totp = (AUTH_MODE in ("totp", "both") and (not ok_static)
                       and verify_totp(pw))
            if ok_static or ok_totp:
                self._clear_fail()
                tok = secrets.token_urlsafe(32)
                SESSIONS[tok] = {"exp": time.time() + SESSION_HOURS * 3600,
                                 "ip": self._client_ip()}
                cookie = (f"sid={tok}; Path=/; HttpOnly; SameSite=Strict; "
                          f"Max-Age={SESSION_HOURS * 3600}")
                if IS_TLS:
                    cookie += "; Secure"
                return self._json({"ok": True}, extra={"Set-Cookie": cookie})
            self._note_fail()
            left2 = MAX_FAILS - len(FAILS[self._client_ip()])
            what = {"totp": "动态码", "both": "密码或动态码", "password": "密码"}[AUTH_MODE]
            return self._json({"error": f"{what}不对（还能试 {max(0, left2)} 次）"}, 401)

        if u.path == "/api/logout":
            tok = self._cookie_token()
            SESSIONS.pop(tok, None)
            return self._json({"ok": True}, extra={"Set-Cookie": "sid=; Path=/; Max-Age=0"})

        if not self._session_ok():
            return self._json({"error": "未登录或会话已过期，请刷新页面重新登录"}, 401)

        if u.path == "/api/config":
            body = self._body()
            host = (body.get("host") or "").strip()
            host = host.replace("http://", "").replace("https://", "").rstrip("/")
            if host.endswith("/api"):
                host = host[:-4]
            cfg = load_cfg()
            cfg["host"] = host
            cfg.setdefault("scheme", "http")
            cfg.setdefault("strategy", "max")
            cfg.setdefault("timeout", 15)
            cfg.setdefault("log_dir", OUT_DIR)
            # 把用过的地址累积进 presets，方便下次直接点
            prev = [str(x) for x in (cfg.get("presets") or []) if str(x).strip()]
            presets = [host] + [x for x in prev if x != host]
            cfg["presets"] = presets[:8]
            persisted = save_cfg(cfg)
            return self._json({
                "ok": True, "host": host, "persisted": persisted,
                "presets": cfg["presets"],
                "note": "" if persisted else
                        "服务器上的 eval_config.json 是只读的（挂载时带了 :ro），"
                        "地址只记住了这个浏览器；想让所有人共用，把 compose 里的 :ro 去掉后重建容器",
            })

        if u.path == "/api/parse":
            body = self._body()
            txt = body.get("text") or ""
            if len(txt) > 500_000:
                return self._json({"error": "名单太大了（超过 50 万字符），请分批"}, 413)
            rows, bad = parse_text(txt)
            lg = ledger_today()
            for r in rows:
                r["done_today"] = r["userName"] in lg
            return self._json({"accounts": rows, "bad": bad, "total": len(rows)})

        if u.path == "/api/run":
            return self._run()

        return self._json({"error": "not found"}, 404)

    # ---- 跑批量 ----
    def _run(self):
        body = self._body()
        text = body.get("text") or ""
        dry = bool(body.get("dry"))
        force = bool(body.get("force"))
        conc = max(1, min(int(body.get("concurrency") or 3), 6))

        # 账号之间的间隔（秒）。设了间隔就自动改成串行 —— 并发下讨论间隔没意义。
        try:
            interval = float(body.get("interval") or 0)
        except (TypeError, ValueError):
            interval = 0.0
        interval = max(0.0, min(interval, 60.0))
        if interval > 0:
            conc = 1

        if len(text) > 500_000:
            return self._json({"error": "名单太大了（超过 50 万字符），请分批提交"}, 413)
        rows, bad = parse_text(text)
        if not rows:
            return self._json({"error": "没有解析出账号，检查格式：姓名 账号 密码"}, 400)
        if len(rows) > 500:
            return self._json({"error": f"一次最多 500 个账号，当前 {len(rows)} 个，请分批"}, 400)

        cfg = load_cfg()
        if not host_ok(cfg.get("host")):
            return self._json({"error": "还没填服务器地址"}, 400)

        # 注意：不要让并发请求互相覆盖全局日志路径
        # 同一时间只跑一个批次：防止手抖连点、或多开标签页把同一批人交两遍
        if not _RUN_LOCK.acquire(blocking=False):
            return self._json({"error": "已经有一个任务在跑了，等它结束再点（防止重复提交）"}, 429)

        hq.LOG_PATH = os.path.join(OUT_DIR, f"web_{datetime.date.today():%Y%m%d}.log")
        done = ledger_today()

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for k, v in self._security_headers().items():
            self.send_header(k, v)
        self.end_headers()

        lock = threading.Lock()
        q_out = queue.Queue()

        def emit(obj):
            with lock:
                try:
                    self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    pass

        emit({"type": "start", "total": len(rows), "dry": dry,
              "interval": interval, "concurrency": conc,
              "bad": bad[:10], "host": cfg["host"]})

        try:
            probe = hq.Client(cfg["host"], scheme=cfg.get("scheme", "http"))
            probe.ensure_scheme()
            if probe.base.startswith("https://"):
                cfg["scheme"] = "https"
        except Exception:
            pass

        def work(i, acc):
            # 第一个不等；后面的按「间隔 × 0.8~1.3 的随机抖动」等，
            # 固定节拍反而更像脚本，抖动一下更接近人手点的节奏
            if interval > 0 and i > 1:
                time.sleep(interval * random.uniform(0.8, 1.3))
            try:
                r = process_one(acc, cfg, dry, force, done)
            except Exception as e:
                r = {"name": acc.get("name", ""), "userName": acc.get("userName", ""),
                     "status": "FAIL", "msg": f"{type(e).__name__}: {e}", "dept": "", "q": 0}
            r["idx"] = i
            q_out.put(r)

        def drain():
            summary = {"ok": 0, "skip": 0, "fail": 0}
            total = len(rows)
            got = 0
            with ThreadPoolExecutor(max_workers=conc) as ex:
                for i, acc in enumerate(rows, 1):
                    ex.submit(work, i, acc)
                for _ in range(total):
                    try:
                        r = q_out.get(timeout=300)
                    except queue.Empty:
                        # 不再静默结束：把没回来的补成「超时」告诉前端
                        emit({"type": "item", "idx": 0, "name": "（超时）", "userName": "",
                              "dept": "", "q": 0, "status": "FAIL",
                              "msg": f"等待超过 300 秒，{total - got} 个账号没有返回"})
                        summary["fail"] += 1
                        break
                    got += 1
                    summary[{"OK": "ok", "SKIP": "skip", "FAIL": "fail"}[r.get("status", "FAIL")]] += 1
                    emit({"type": "item", **r})
            emit({"type": "done", "summary": summary, "dry": dry,
                  "date": today(), "ledger": len(ledger_today())})

        def runner():
            try:
                drain()
            finally:
                try:
                    _RUN_LOCK.release()
                except Exception:
                    pass

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        t.join()


def main():
    global PASSWORD, ALLOW_IPS, TRUST_PROXY, IS_TLS, IS_SELF_SIGNED, NO_HSTS, OUT_DIR, LEDGER
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--password", help="访问密码（监听 0.0.0.0 时必设）")
    ap.add_argument("--token", help="（旧参数，等同 --password）")
    ap.add_argument("--tls-cert", help="HTTPS 证书路径（fullchain.pem）")
    ap.add_argument("--tls-key", help="HTTPS 私钥路径（privkey.pem）")
    ap.add_argument("--self-signed", action="store_true", help="自动生成自签证书")
    ap.add_argument("--allow-ip", help="IP 白名单，逗号分隔")
    ap.add_argument("--trust-proxy", action="store_true",
                    help="放在 Nginx/Caddy/Cloudflare 后面时打开")
    ap.add_argument("--no-hsts", action="store_true",
                    help="不发送 HSTS 头（浏览器会缓存「必须用 HTTPS」，自签证书时尤其别发）")
    ap.add_argument("--gen-totp", action="store_true",
                    help="生成一个新的动态码密钥并打印（填到 eval_config.json 的 totp_secret）")
    ap.add_argument("--allow-insecure", action="store_true",
                    help="监听 0.0.0.0 且不设密码时允许启动（不推荐）")
    # Docker / 1Panel 部署时，用环境变量比命令行参数安全（ps 能看到命令行）
    ap.add_argument("--no-env", action="store_true", help="忽略 HQHS_* 环境变量")
    a = ap.parse_args()

    if a.gen_totp:
        sec = gen_totp_secret()
        print("新的动态码密钥（填到 eval_config.json 的 totp_secret）：")
        print()
        print("  " + sec)
        print()
        print("用 Authenticator（Google / 微软 / 1Password）添加这个链接：")
        print()
        print("  " + otpauth_url(sec))
        print()
        print("当前验证码：" + totp_now(sec))
        return

    if not a.no_env:
        a.password = a.password or os.environ.get("HQHS_PASSWORD")
        a.token = a.token or os.environ.get("HQHS_TOKEN")
        if os.environ.get("HQHS_TRUST_PROXY") in ("1", "true", "yes"):
            a.trust_proxy = True
        if os.environ.get("HQHS_ALLOW_INSECURE") in ("1", "true", "yes"):
            a.allow_insecure = True
        if os.environ.get("HQHS_ALLOW_IP") and not a.allow_ip:
            a.allow_ip = os.environ["HQHS_ALLOW_IP"]
        _tls = (os.environ.get("HQHS_TLS") or "").lower()
        if _tls in ("self-signed", "selfsigned", "1", "on", "yes"):
            a.self_signed = True
        elif _tls in ("off", "none", "0", "no"):
            a.self_signed = False
        if os.environ.get("HQHS_PORT"):
            try:
                a.port = int(os.environ["HQHS_PORT"])
            except ValueError:
                pass

    pw_plain = a.password or a.token
    global TOTP_SECRET, TOTP_WINDOW, AUTH_MODE
    _cfg0 = load_cfg()
    _sec = (os.environ.get("HQHS_TOTP_SECRET") or _cfg0.get("totp_secret") or "").strip()
    if _sec:
        TOTP_SECRET = re.sub(r"\s+", "", _sec).upper()
    try:
        TOTP_WINDOW = max(0, min(int(_cfg0.get("totp_window", 1)), 5))
    except (TypeError, ValueError):
        TOTP_WINDOW = 1

    # 认证方式：配置里显式写了就听配置；否则「配了密钥就只用动态码，没配就用密码」
    _mode = str(_cfg0.get("auth_mode") or "").strip().lower()
    if _mode in ("password", "totp", "both"):
        AUTH_MODE = _mode
    else:
        AUTH_MODE = "totp" if TOTP_SECRET else "password"

    PASSWORD = pw_hash(pw_plain) if pw_plain else None
    NO_HSTS = bool(a.no_hsts)
    TRUST_PROXY = a.trust_proxy
    if a.allow_ip:
        ALLOW_IPS = {x.strip() for x in a.allow_ip.split(",") if x.strip()}

    os.chdir(ROOT)

    # 启动时就探一次 AES 后端，页面和日志能立刻看到走的是哪条路
    try:
        hq.aes_encrypt("warmup")
    except Exception as e:
        print(f" ! AES 预热失败: {e}")

    exposed = a.host not in ("127.0.0.1", "localhost", "::1")
    if exposed and not PASSWORD and not TOTP_SECRET and not a.allow_insecure:
        print("!" * 60)
        print(" 拒绝启动：正在把服务暴露到本机以外，但没有设访问密码。")
        print(" 任何人都能看到名单、替你提交评价。")
        print("")
        print(f"   python web/server.py --host {a.host} --port {a.port} "
              f"--password '你的密码' --self-signed")
        print("")
        print(" 确实无所谓（仅可信内网）就加 --allow-insecure")
        print("!" * 60)
        sys.exit(1)

    # 先定好输出目录 —— 后面的证书、日志、台账都往这里写
    _out_primary = OUT_DIR
    OUT_DIR = resolve_out_dir()
    LEDGER = os.path.join(OUT_DIR, "submitted.json")
    _out_fallback = OUT_DIR != _out_primary

    cert, key = a.tls_cert, a.tls_key
    if a.self_signed and not cert:
        IS_SELF_SIGNED = True
        cert = os.path.join(OUT_DIR, "tls", "cert.pem")
        key = os.path.join(OUT_DIR, "tls", "key.pem")
        if not os.path.exists(cert):
            print("[*] 生成自签证书 …")
            make_self_signed(cert, key)
        print(f"    证书: {cert}")
    IS_TLS = bool(cert and key and os.path.exists(cert))

    threading.Thread(target=_gc_loop, daemon=True).start()

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    if IS_TLS:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)

    scheme = "https" if IS_TLS else "http"
    cfg = load_cfg()
    _cfg_writable = cfg_writable()
    print("=" * 56)
    print(" 伙食评价 · 网页版")
    print("=" * 56)
    print(f" 打开: {scheme}://{a.host if a.host != '0.0.0.0' else '127.0.0.1'}:{a.port}")
    print(f" 服务器地址: {cfg.get('host') if host_ok(cfg.get('host')) else '（还没填，在网页里填）'}")
    print(f" 版本    : {VERSION}")
    print(f" 配置文件: {'可写（网页里改地址会保存）' if _cfg_writable else '只读（网页里改地址只记在浏览器）'}")
    print(f" 数据目录: {OUT_DIR}")
    if _out_fallback:
        print(f" ! {_out_primary} 写不进去（容器内 uid 1000 对宿主机目录没权限），已自动改用容器内目录。")
        print("   容器重建后今天的台账会丢。要修就执行：")
        print(f"     docker exec -u root hqhs-eval chown -R 1000:1000 {_out_primary}")
    print(f" AES 后端 : {hq.AES_BACKEND}")
    _auth_desc = {"totp": "动态码（TOTP）", "both": "密码或动态码", "password": "静态密码"}[AUTH_MODE]
    _auth_on = bool(PASSWORD or TOTP_SECRET)
    print(f" 访问密码: {_auth_desc if _auth_on else '未启用'}（登录后 {SESSION_HOURS} 小时免登录）")
    if TOTP_SECRET:
        print(f" 动态码  : 当前 {totp_now(TOTP_SECRET)}（下一个 {totp_now(TOTP_SECRET, 1)}，容差 ±{TOTP_WINDOW * 30} 秒）")
        print(f"           导入: {otpauth_url(TOTP_SECRET)}")
    if AUTH_MODE == "both" and PASSWORD:
        print("           静态密码也接受")
    print(f" HTTPS   : {'开' if IS_TLS else '关'}")
    if ALLOW_IPS:
        print(f" IP 白名单: {', '.join(sorted(ALLOW_IPS))}")
    if not PASSWORD and not TOTP_SECRET:
        print(" ! 没有访问密码 —— 任何能打开这个网址的人都能看到名单、替你提交")
        if ALLOW_IPS:
            print(f"   已启用 IP 白名单，只放行: {', '.join(sorted(ALLOW_IPS))}")
        elif a.host == "0.0.0.0":
            print("   建议至少加 --allow-ip 限制来源，或者在反向代理/防火墙那一层做限制")
    if exposed and not IS_TLS:
        print(" ! 明文 HTTP 暴露在网络上 —— 密码和名单会被抓包看到，建议加 --self-signed 或放反代后面")
    print(" Ctrl+C 停止")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
