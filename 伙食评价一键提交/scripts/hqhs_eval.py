#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hqhs_eval.py — 「智慧后勤」伙食满意度测评 一键评价提交

逆向自 app/base.apk (com.xykj.hqhs 4.16.2)

真实调用链（jadx: com.xykj.evaluation.ui.FiremanEvaluationActivity）
--------------------------------------------------------------
1. 登录      POST /api/learnworld-canteen/api/loginByAppV2?userName=<AES>&passWord=<AES>
             -> UserRes{access_token, userId, orgId, orgGrade, dept_name, role_name}
2. 取当天模板 POST /api/learnworld-canteen/api/appraiseGrassDetail?id=&grade=
             -> DataBean{satisfiedList[], superviseList[], id(saveId), orgId, orgName, dateStr}
             新增评价时 id 和 grade 都传空串（FiremanEvaluationManagerActivity:146 就这么干的）
3. 提交      POST /api/learnworld-canteen/api/appraiseGrassSave   body=DataBean
             type="1"(TYPE_APPRAISE_REAL)  checkOrgId=orgId  source="app"

认证与公共参数（CommonInterceptor）
--------------------------------------------------------------
Authorization: Basic c2FiZXI6c2FiZXJfc2VjcmV0        (saber:saber_secret)
Blade-Auth:    bearer <access_token>
query 自动附加: orgName=<dept_name> & userId=<userId> & orgId=<orgId>
密码加密: AES/ECB/PKCS5Padding，key="metagross-zhihuihouqin-shanxixueyu-400-151-6766"
          截/补到 32 字符 -> AES-256，输出大写 hex

用法
--------------------------------------------------------------
  python hqhs_eval.py -c eval_config.json --dry-run     # 只看要提交什么
  python hqhs_eval.py -c eval_config.json               # 真提交
  python hqhs_eval.py -c eval_config.json --status      # 只看本周评价状态，不提交
  python hqhs_eval.py -c eval_config.json --loop 7d     # 每周自动跑
  python hqhs_eval.py --host 10.0.0.8:8080 -u 张三 -p 123456
"""
import argparse, json, os, sys, threading, time, datetime

try:
    import requests
except ImportError:
    sys.exit("pip install requests")
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as _padding
    _HAS_CRYPTO = True
except Exception:
    Cipher = algorithms = modes = _padding = None
    _HAS_CRYPTO = False

# ============ 逆向得到的内置常量 ============
AES_KEY    = "metagross-zhihuihouqin-shanxixueyu-400-151-6766"
BASIC_AUTH = "Basic c2FiZXI6c2FiZXJfc2VjcmV0"      # saber:saber_secret
UA = ("Mozilla/5.0 (Linux; Android 13; MI 8) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Mobile Safari/537.36")
TYPE_APPRAISE_REAL = "1"

API = {
    "login":  "learnworld-canteen/api/loginByAppV2",
    "detail": "learnworld-canteen/api/appraiseGrassDetail",
    "save":   "learnworld-canteen/api/appraiseGrassSave",
    "page":   "learnworld-canteen/api/appraiseGrassPage",
}

LOG_PATH = None
_LOG_LOCK = threading.Lock()

_LOG_BROKEN = False


def log(msg):
    """写日志。日志文件写不进去（比如目录只读、容器里权限不对）时只打印，绝不抛异常 ——
    否则一个日志失败会把整批提交带崩，看起来像"提交失败"，其实可能已经提交成功了。"""
    global _LOG_BROKEN
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with _LOG_LOCK:
        print(line, flush=True)
        if not LOG_PATH or _LOG_BROKEN:
            return
        try:
            os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            _LOG_BROKEN = True
            print(f"[警告] 日志文件写不进去（{e}），后续日志只打印不落盘。"
                  f"检查 {os.path.dirname(LOG_PATH)} 的权限", flush=True)

class ApiError(RuntimeError):
    """服务端明确拒绝（success=false）。code 是业务码。"""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code

    @property
    def is_daily_limit(self):
        return "异常了，请联系管理员" in str(self) or "上限" in str(self)


# ============ AES (AESUtils3 复刻) ============
def env_report() -> dict:
    """环境自检：版本 + AES 往返。网页上的「自检」按钮就调这个。"""
    import platform
    rep = {"python": platform.python_version(), "ok": True, "problems": []}
    for name in ("requests", "cryptography"):
        try:
            mod = __import__(name)
            rep[name] = getattr(mod, "__version__", "?")
        except Exception as e:
            rep[name] = None
            rep["ok"] = False
            rep["problems"].append(f"{name} 导入失败: {e}")
    try:
        c = aes_encrypt("selftest")
        rep["aes"] = c
        rep["aes_backend"] = AES_BACKEND
        # 最硬的校验：和 App 里算出来的已知值比
        if aes_encrypt("zhangsan") != "8A482F70744DA1853EDA33EC908B9A04":
            raise RuntimeError("AES 结果与 App 不一致")
    except Exception as e:
        rep["ok"] = False
        rep["aes"] = None
        rep["problems"].append(f"AES 自检失败: {type(e).__name__}: {e}")
    if rep.get("cryptography"):
        try:
            import inspect
            params = list(inspect.signature(Cipher.__init__).parameters)
            rep["cipher_api"] = "old(backend 在前)" if params[:3] == ["self", "backend", "algorithm"] else "new"
        except Exception:
            rep["cipher_api"] = "?"
    return rep


def _make_key(password: str = AES_KEY) -> bytes:
    s = password or ""
    buf = s + "0" * max(0, 32 - len(s))     # 补 '0'，再截断到 32
    return buf[:32].encode("utf-8")

# cryptography 只是「快」；装不上 / 版本不兼容时自动退回纯 Python 实现
AES_BACKEND = "unknown"


def _load_pure():
    import importlib.util as _ilu
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "aes_pure.py")
    spec = _ilu.spec_from_file_location("aes_pure", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.encrypt_hex


try:
    _pure_aes_hex = _load_pure()
except Exception:
    _pure_aes_hex = None

# 想强制走纯 Python 实现来验证（或绕开库的问题）：
#   Linux/Mac:  HQHS_FORCE_PURE_AES=1 python scripts/hqhs_eval.py --status
#   Windows:    set HQHS_FORCE_PURE_AES=1 然后运行
if os.environ.get("HQHS_FORCE_PURE_AES") == "1":
    _HAS_CRYPTO = False


def aes_encrypt(plain: str) -> str:
    """AES/ECB/PKCS5 + 大写 hex，与 App 的 AESUtils3 一致。

    先用 cryptography（快），任何异常都回退到内置纯 Python 实现 ——
    这样 cryptography 没装、版本不兼容、Cipher 参数对不上（backend 那类报错），都照样能算。
    """
    global AES_BACKEND
    key = _make_key()
    if _HAS_CRYPTO:
        try:
            padder = _padding.PKCS7(128).padder()
            data = padder.update(plain.encode("utf-8")) + padder.finalize()
            enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
            out = (enc.update(data) + enc.finalize()).hex().upper()
            AES_BACKEND = "cryptography"
            return out
        except Exception:
            pass                     # 静默回退，不把库的怪错误抛给用户
    if _pure_aes_hex is not None:
        AES_BACKEND = "pure-python"
        return _pure_aes_hex(plain, key)
    raise RuntimeError("AES 不可用：cryptography 调不通，且内置实现加载失败")


def aes_decrypt(hexstr: str) -> str:
    """只给自检用；纯 Python 模式下返回 None（业务上只加密不解密）"""
    if not _HAS_CRYPTO:
        return None
    try:
        key = _make_key()
        dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        raw = dec.update(bytes.fromhex(hexstr)) + dec.finalize()
        unp = _padding.PKCS7(128).unpadder()
        return (unp.update(raw) + unp.finalize()).decode("utf-8")
    except Exception:
        return None


# ============ HTTP 客户端 ============
class Client:
    def __init__(self, host, timeout=15, scheme="http"):
        host = host.strip().rstrip("/")
        if host.startswith(("http://", "https://")):
            self.base = host + "/api/"
        else:
            self.base = f"{scheme}://{host}/api/"
        self.timeout = timeout
        self.s = requests.Session()
        self.user = None

    def ensure_scheme(self):
        """http 被 301/308 跳到 https（或 http 根本不通）时自动切到 https。
        切换前先确认 https 真的可达，避免把能用的 http 换掉。"""
        if not self.base.startswith("http://"):
            return
        r = None
        try:
            r = self.s.get(self.base, timeout=8, allow_redirects=False)
        except Exception:
            r = None
        loc = ((r.headers.get("Location", "") or "") if r is not None else "")
        need = (r is None) or (r.status_code in (301, 302, 307, 308) and "https://" in loc)
        if not need:
            return
        alt = "https://" + self.base[len("http://"):]
        try:
            self.s.get(alt, timeout=8, allow_redirects=False)
        except Exception:
            return                      # https 也不通，保持 http 原样
        self.base = alt
        log(f"已切换 HTTPS: {self.base}")

    # 公共参数与头（复刻 CommonInterceptor）
    def _common_query(self, url_has_user):
        q = {}
        if self.user:
            q["orgName"] = self.user.get("dept_name") or ""
            if not url_has_user.get("userId"):
                q["userId"] = self.user.get("userId") or ""
            if not url_has_user.get("orgId"):
                q["orgId"] = self.user.get("orgId") or ""
        return q

    def _headers(self):
        h = {
            "Authorization": BASIC_AUTH,
            "User-Agent": UA,
            "Accept": "*/*",
            "Connection": "Keep-Alive",
        }
        if self.user and self.user.get("access_token"):
            h["Blade-Auth"] = "bearer " + self.user["access_token"]
        return h

    def post(self, path, params=None, body=None, is_login=False):
        params = dict(params or {})
        url_has = {"userId": "userId" in params, "orgId": "orgId" in params}
        if not is_login:
            for k, v in self._common_query(url_has).items():
                params.setdefault(k, v)
        url = self.base + path
        headers = self._headers()
        kwargs = {"params": params, "headers": headers, "timeout": self.timeout}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            kwargs["data"] = json.dumps(body, ensure_ascii=False).encode("utf-8")
        r = self.s.post(url, **kwargs)
        try:
            j = r.json()
        except Exception:
            raise RuntimeError(f"非 JSON 响应 HTTP {r.status_code}: {r.text[:300]}")
        return r, j

    def call(self, path, params=None, body=None, is_login=False):
        r, j = self.post(path, params, body, is_login)
        code = j.get("code")
        ok = bool(j.get("success")) or str(code) in ("200", "0")
        if not ok:
            raise ApiError(f"{j.get('msg') or j} (code={code}, http={r.status_code})", code)
        return j.get("data")

# ============ 业务 ============
def login(c, user_name, pass_word):
    data = c.call(API["login"],
                  {"userName": aes_encrypt(user_name), "passWord": aes_encrypt(pass_word)},
                  is_login=True)
    if not data:
        raise RuntimeError("登录返回空")
    c.user = data
    log(f"登录成功: {data.get('userName') or user_name} | userId={data.get('userId')} "
        f"orgId={data.get('orgId')} orgGrade={data.get('orgGrade')} "
        f"role={data.get('role_name')} dept={data.get('dept_name')}")
    return data

def pick_choice(item, strategy, fixed_score=None):
    """从 optionNames/optionGrades 里挑一个选项值。
    optionGrades 形如 "5,4,3,2,1"，optionNames 形如 "很满意,满意,一般,不满意,很不满意"
    strategy: max(最高分) / first(第一项) / fixed(指定分值)
    """
    grades = [g.strip() for g in (item.get("optionGrades") or "").split(",") if g.strip()]
    names = [n.strip() for n in (item.get("optionNames") or "").split(",") if n.strip()]
    if not grades:
        return None, None, names
    if fixed_score is not None:
        want = str(fixed_score)
        if want in grades:
            idx = grades.index(want)
            return grades[idx], (names[idx] if idx < len(names) else ""), names
    idx = 0
    if strategy == "first":
        idx = 0                                   # 就取服务端给的第一个选项
    else:
        try:                                      # max（默认）：数值最大；非数值回落第一个
            nums = [float(g) for g in grades]
            idx = nums.index(max(nums))
        except ValueError:
            idx = 0
    return grades[idx], (names[idx] if idx < len(names) else ""), names

def get_detail(c, save_id="", grade=""):
    data = c.call(API["detail"], {"id": save_id, "grade": grade})
    if not data:
        raise RuntimeError("服务端没有下发待评价任务（今天这条已经交过 / 不在用餐评价时间窗 / "
                           "或本周任务已全部完成）。用 --status 看本周已交记录。")
    return data

def fill_and_save(c, detail, strategy="max", fixed_score=None, dry_run=False,
                  comment="", verbose=True):
    satisfied = detail.get("satisfiedList") or []
    supervise = detail.get("superviseList") or []
    if not satisfied and not supervise:
        raise RuntimeError("题目列表为空 —— 服务端认为当前没有需要你评价的任务"
                           "（多半是今天已交过）。用 --status 查看本周记录。")

    preview = []
    for group_name, group in (("满意度测评", satisfied), ("日常监督测评", supervise)):
        for i, item in enumerate(group, 1):
            choice, choice_name, all_names = pick_choice(item, strategy, fixed_score)
            if choice is None:
                raise RuntimeError(f"{group_name} 第{i}题没有可选项: {item.get('appraiseSubName')}")
            item["choice"] = choice
            preview.append(f"  {group_name} 第{i}题 {item.get('appraiseSubName')}: "
                           f"选 {choice} ({choice_name})  可选={all_names}")

    payload = {
        "satisfiedList": satisfied,
        "superviseList": supervise,
        "type": TYPE_APPRAISE_REAL,
        "checkOrgId": detail.get("orgId") or "",
        "orgId": detail.get("orgId") or "",
        "id": detail.get("id") or detail.get("f62id") or "",
        "userId": (c.user or {}).get("userId") or "",
        "source": "app",
        "orgName": detail.get("orgName") or "",
        "dateStr": detail.get("dateStr") or "",
    }

    if verbose:
        log(f"评分方案（{len(satisfied)} 项满意度 + {len(supervise)} 项监督）:")
        for line in preview:
            log(line)
    log(f"saveId={payload['id']} orgId={payload['orgId']} orgName={payload['orgName']} "
        f"dateStr={payload['dateStr']}")

    if dry_run:
        if verbose:
            log("[DRY] 将要提交的 body:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return True

    res = c.call(API["save"], body=payload)
    log(f"提交成功: {res}")
    return True

def show_status(c):
    """查本周评价记录（appraiseGrassPage，grade=<orgGrade> type=1）"""
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    sunday = monday + datetime.timedelta(days=6)
    try:
        data = c.call(API["page"], {
            "current": 1, "size": 10,
            "grade": (c.user or {}).get("orgGrade") or "",
            "type": TYPE_APPRAISE_REAL,
            "startDateStr": monday.strftime("%Y-%m-%d"),
            "endDateStr": sunday.strftime("%Y-%m-%d"),
            "orgId": (c.user or {}).get("orgId") or "",
        })
    except Exception as e:
        log(f"查记录失败: {e}")
        return
    records = (data or {}).get("records") or []
    log(f"本机构本周（{monday} ~ {sunday}）共 {len(records)} 条记录（appraiseGrassPage 按 orgId 查，含机构内其他人）:")
    for r in records:
        log(f"  {r.get('dateStr')} {r.get('timeStr','')} {r.get('orgName','')} "
            f"满意度={r.get('satisfiedScore')} 监督分={r.get('superviseScore')} id={r.get('id')}")
    if not records:
        log("  还没有提交记录 —— 今天可以交")

# ============ 入口 ============
def load_cfg(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}

def parse_interval(s):
    import re
    m = re.match(r"^(\d+)\s*([smhdw])$", s)
    if not m:
        return 7 * 86400
    n, u = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[u]

def run_once(cfg, args):
    global LOG_PATH
    LOG_PATH = os.path.join(cfg.get("log_dir", "out"), "hqhs_eval.log")

    host = args.host or cfg.get("host")
    user = args.user or cfg.get("userName")
    pwd = args.password or cfg.get("passWord")
    if (not host) or str(host).startswith("[") or "填" in str(host):
        sys.exit("还没填服务器地址：打开 eval_config.json 把 host 改成手机 App 里那个地址")
    if not user or not pwd:
        sys.exit("缺账号密码：写在 eval_config.json 的 userName / passWord，或用 -u -p")

    scheme = args.scheme or cfg.get("scheme", "http")
    c = Client(host, timeout=cfg.get("timeout", 15), scheme=scheme)
    log(f"目标: {c.base}")
    c.ensure_scheme()

    login(c, user, pwd)

    if args.status:
        show_status(c)
        return True

    strategy = cfg.get("strategy", "max")
    fixed = args.score if args.score is not None else cfg.get("fixedScore")
    # 新增评价时 grade 传用户的 orgGrade（App: ObjectUtils.isNull("")==true 会回落到 getUserGrade()）
    grade = cfg.get("grade") or (c.user or {}).get("orgGrade") or ""
    detail = get_detail(c, cfg.get("saveId", ""), grade)
    return fill_and_save(c, detail, strategy=strategy, fixed_score=fixed,
                         dry_run=args.dry_run, comment=cfg.get("comment", ""))

def main():
    ap = argparse.ArgumentParser(description="伙食满意度测评 一键提交")
    ap.add_argument("-c", "--config", default="eval_config.json")
    ap.add_argument("--host")
    ap.add_argument("--scheme", choices=["http", "https"], help="默认取配置，auto 会跟随服务器跳转")
    ap.add_argument("-u", "--user")
    ap.add_argument("-p", "--password")
    ap.add_argument("--score", type=float, help="指定分值，如 5（默认取每题最高分）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true", help="只查本周评价记录")
    ap.add_argument("--loop", help="常驻周期，如 7d")
    a = ap.parse_args()

    cfg = load_cfg(a.config)
    if a.loop:
        iv = parse_interval(a.loop)
        log(f"常驻模式，每 {iv}s 提交一次")
        while True:
            try:
                run_once(cfg, a)
            except Exception as e:
                log(f"本轮失败: {type(e).__name__}: {e}")
            log(f"下次: {datetime.datetime.now() + datetime.timedelta(seconds=iv):%Y-%m-%d %H:%M:%S}")
            time.sleep(iv)
    try:
        sys.exit(0 if run_once(cfg, a) else 1)
    except Exception as e:
        log(f"失败: {type(e).__name__}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
