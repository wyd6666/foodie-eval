#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hqhs_batch.py — 多账号批量「一键评价提交」

复用 hqhs_eval.py 里已经验证过的登录（AES）/取模板/逐题打分/提交逻辑，
把「一个账号一条命令」变成「一份名单一条命令」。

账号来源（任选）:
  accounts.json     [{"name":"张三","userName":"...","passWord":"..."}, ...]
  accounts.csv      name,userName,passWord   （首行表头可省略；支持从 Excel 直接粘）

用法:
  python scripts/hqhs_batch.py -a accounts.json --dry-run      # 全员预演，不提交
  python scripts/hqhs_batch.py -a accounts.json                # 真交
  python scripts/hqhs_batch.py -a accounts.csv --status        # 只查各人本周交了几条
  python scripts/hqhs_batch.py -a accounts.json --only 张三,李四  # 只跑指定人
  python scripts/hqhs_batch.py -a accounts.json --concurrency 3  # 并发（默认串行更稳）
  python scripts/hqhs_batch.py -a accounts.json --retry 2        # 网络失败重试次数

判定口径:
  OK    提交成功
  SKIP  服务端没下发任务（今天已交 / 不在时间窗）—— 不算失败
  FAIL  登录失败、密码错、权限不足、提交被拒
"""
import argparse, csv, importlib.util, json, os, random, sys, time, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# 本地台账：谁哪天交过了。用来防止「一天点两次就交两次」。
LEDGER = os.path.join(ROOT, "out", "submitted.json")
_LEDGER_LOCK = __import__("threading").Lock()


def _today():
    return datetime.date.today().isoformat()


def load_ledger():
    if not os.path.exists(LEDGER):
        return {}
    try:
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ledger(lg):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    # 只留最近 30 天，避免文件无限长大
    keep = sorted(lg.keys())[-30:]
    lg = {k: lg[k] for k in keep}
    with _LEDGER_LOCK:
        tmp = LEDGER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LEDGER)


def ledger_mark(user_name):
    lg = load_ledger()
    lg.setdefault(_today(), {})[user_name] = datetime.datetime.now().strftime("%H:%M:%S")
    save_ledger(lg)


def ledger_today():
    return load_ledger().get(_today(), {})

# ---- 复用主脚本 ----
spec = importlib.util.spec_from_file_location("hqhs_eval", os.path.join(HERE, "hqhs_eval.py"))
hq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hq)


def now():
    return datetime.datetime.now()


def stamp():
    return now().strftime("%Y%m%d_%H%M%S")


# ---------------- 名单读取 ----------------
def load_accounts(path):
    if not os.path.exists(path):
        sys.exit(f"[!] 找不到名单文件 {path}\n"
                 f"    建一个 accounts.json: [{{\"name\":\"张三\",\"userName\":\"...\",\"passWord\":\"...\"}}]")
    if path.lower().endswith(".csv"):
        rows = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.reader(f):
                if not r or not "".join(r).strip():
                    continue
                cells = [c.strip() for c in r]
                # 跳过表头
                if cells[0] in ("name", "姓名", "姓名/账号"):
                    continue
                if len(cells) >= 3:
                    rows.append({"name": cells[0], "userName": cells[1], "passWord": cells[2]})
                elif len(cells) == 2:
                    rows.append({"name": cells[0], "userName": cells[0], "passWord": cells[1]})
        return rows
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("accounts", [])
    return data


# ---------------- 单账号处理 ----------------
def process(acc, idx, total, cfg, args):
    name = (acc.get("name") or acc.get("userName") or f"#{idx}").strip()
    user = str(acc.get("userName") or "").strip()
    pwd = str(acc.get("passWord") or "")
    res = {"idx": idx, "name": name, "userName": user, "status": "FAIL",
           "msg": "", "dept": "", "questions": 0, "at": now().strftime("%H:%M:%S")}

    tag = f"[{idx}/{total}] {name}"
    if not user or not pwd:
        res["msg"] = "名单里缺 userName/passWord"
        print(f"{tag}  ✗ {res['msg']}", flush=True)
        return res

    # 本地台账：今天已经交过的人直接跳过（防止一天点两次就交两次）
    if getattr(args, "skip_today", False) and not args.status:
        done_at = ledger_today().get(user)
        if done_at:
            res["status"] = "SKIP"
            res["msg"] = f"今天 {done_at} 已交过（本地台账）"
            print(f"{tag}  · 跳过：{res['msg']}", flush=True)
            return res

    try:
        c = hq.Client(cfg["host"], timeout=cfg.get("timeout", 15), scheme=cfg.get("scheme", "http"))
        c.ensure_scheme()
        hq.login(c, user, pwd)
        res["dept"] = (c.user or {}).get("dept_name") or ""
        res["role"] = (c.user or {}).get("role_name") or ""

        if args.status:
            today = datetime.date.today()
            monday = today - datetime.timedelta(days=today.weekday())
            data = c.call(hq.API["page"], {
                "current": 1, "size": 50,
                "grade": (c.user or {}).get("orgGrade") or "",
                "type": hq.TYPE_APPRAISE_REAL,
                "startDateStr": monday.strftime("%Y-%m-%d"),
                "endDateStr": (monday + datetime.timedelta(days=6)).strftime("%Y-%m-%d"),
                "orgId": (c.user or {}).get("orgId") or "",
            })
            recs = (data or {}).get("records") or []
            res["status"] = "OK"
            res["msg"] = f"本机构本周 {len(recs)} 条记录（按机构统计，非个人）"
            print(f"{tag}  ✓ {res['msg']}  ({res['dept']})", flush=True)
            return res

        grade = cfg.get("grade") or (c.user or {}).get("orgGrade") or ""
        detail = hq.get_detail(c, cfg.get("saveId", ""), grade)
        sat = detail.get("satisfiedList") or []
        sup = detail.get("superviseList") or []
        res["questions"] = len(sat) + len(sup)
        if not sat and not sup:
            res["status"] = "SKIP"
            res["msg"] = "服务端没下发任务（今天已交/不在时间窗）"
            print(f"{tag}  · 跳过：{res['msg']}", flush=True)
            return res

        hq.fill_and_save(c, detail, strategy=cfg.get("strategy", "max"),
                         fixed_score=args.score if args.score is not None else cfg.get("fixedScore"),
                         dry_run=args.dry_run, verbose=not args.quiet)
        res["status"] = "OK"
        res["msg"] = ("预演通过" if args.dry_run else "提交成功") + f"（{len(sat)}满意度+{len(sup)}监督）"
        if not args.dry_run:
            ledger_mark(user)          # 记进台账，同一天不会再交第二次
        print(f"{tag}  ✓ {res['msg']}  ({res['dept']})", flush=True)
        return res

    except hq.ApiError as e:
        if e.is_daily_limit:
            # 服务端说「异常了，请联系管理员」其实就是当天次数上限。
            # 这种情况通常意味着这次（或上一次重试）已经提交成功了，不该算失败。
            res["status"] = "SKIP"
            res["msg"] = "当天评价次数已达上限（视为已交）"
            print(f"{tag}  · 跳过：{res['msg']}", flush=True)
            return res
        msg = str(e)
        if "用户名或密码错误" in msg or "用户名不存在" in msg or "密码" in msg:
            msg = "账号或密码错误"
        elif "Token" in msg:
            msg = "登录态异常"
        res["msg"] = msg
        print(f"{tag}  ✗ {msg}", flush=True)
        return res
    except Exception as e:
        msg = str(e)
        if "用户名或密码错误" in msg or ("密码" in msg and "错误" in msg):
            msg = "账号或密码错误"
        elif "Token" in msg:
            msg = "登录态异常"
        res["msg"] = msg
        print(f"{tag}  ✗ {msg}", flush=True)
        return res


def main():
    ap = argparse.ArgumentParser(description="多账号批量评价提交")
    ap.add_argument("-a", "--accounts", default="accounts.json")
    ap.add_argument("-c", "--config", default="eval_config.json")
    ap.add_argument("--host")
    ap.add_argument("--scheme", choices=["http", "https"])
    ap.add_argument("--score", type=float, help="统一指定分值（默认每题最高分）")
    ap.add_argument("--only", help="只跑这些人，逗号分隔（按 name 或 userName）")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--retry", type=int, default=0, help="单个账号网络失败重试次数")
    ap.add_argument("--interval", type=float, default=0.4,
                    help="每个账号之间的间隔秒数，默认 0.4；想更像人工就设 30~50")
    ap.add_argument("--quiet", action="store_true", help="不逐题打印评分方案，只看汇总")
    ap.add_argument("--skip-today", action="store_true",
                    help="今天已经交过的人直接跳过（查 out/submitted.json 台账）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true", help="只查本周已交条数")
    a = ap.parse_args()

    global cfg
    cfg = hq.load_cfg(a.config)
    cfg["host"] = a.host or cfg.get("host") or ""
    if a.scheme:
        cfg["scheme"] = a.scheme
    if (not cfg["host"]) or cfg["host"].startswith("[") or "填" in cfg["host"]:
        sys.exit("还没填服务器地址：打开 eval_config.json，把 host 改成\n"
                 "   你手机 App 登录页里那个地址（例如 sd.example.gov.cn 或 10.1.2.3:8080，\n"
                 "   不要带 http:// 也不要带 /api/）")

    # 统一的 HTTPS 探测：只做一次，结果写回 cfg 给所有账号复用
    probe = hq.Client(cfg["host"], timeout=cfg.get("timeout", 15), scheme=cfg.get("scheme", "http"))
    probe.ensure_scheme()
    if probe.base.startswith("https://"):
        cfg["scheme"] = "https"
    print(f"目标: {probe.base}")

    accounts = load_accounts(a.accounts)
    if a.only:
        keys = {x.strip() for x in a.only.split(",") if x.strip()}
        accounts = [x for x in accounts if (x.get("name") or "").strip() in keys or str(x.get("userName") or "").strip() in keys]
    if not accounts:
        sys.exit("[!] 名单是空的")

    os.makedirs("out", exist_ok=True)
    hq.LOG_PATH = os.path.join("out", f"batch_{stamp()}.log")

    print("=" * 66)
    print(f"批量{'预演' if a.dry_run else ('查询' if a.status else '评价')} | "
          f"{len(accounts)} 个账号 | {cfg['host']} | {now():%Y-%m-%d %H:%M:%S}")
    print("=" * 66)

    results = []
    total = len(accounts)
    if a.concurrency > 1:
        with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
            futs = {ex.submit(process, acc, i, total, cfg, a): i
                    for i, acc in enumerate(accounts, 1)}
            for fut in as_completed(futs):
                results.append(fut.result())
        results.sort(key=lambda r: r["idx"])
    else:
        for i, acc in enumerate(accounts, 1):
            r = process(acc, i, total, cfg, a)
            # 单账号失败重试（只重试网络类，不重试密码错）
            tries = 0
            while (r["status"] == "FAIL" and tries < a.retry
                   and not any(k in r["msg"] for k in ("密码", "账号", "上限"))):
                tries += 1
                print(f"      重试 {tries}/{a.retry} ...", flush=True)
                time.sleep(2)
                r = process(acc, i, total, cfg, a)
            results.append(r)
            # 每个账号之间歇一下，带 ±20% 抖动 —— 固定节拍反而更像脚本
            iv = max(0.0, min(float(a.interval or 0), 60.0))
            if iv > 0 and i < total:
                time.sleep(iv * random.uniform(0.8, 1.2))

    ok = [r for r in results if r["status"] == "OK"]
    skip = [r for r in results if r["status"] == "SKIP"]
    fail = [r for r in results if r["status"] == "FAIL"]

    print("\n" + "=" * 66)
    print(f"汇总: 成功 {len(ok)} | 跳过 {len(skip)} | 失败 {len(fail)} | 共 {total}")
    if fail:
        print("-" * 66)
        for r in fail:
            print(f"  ✗ {r['name']:<12} {r['msg']}")
    if skip:
        print("-" * 66)
        for r in skip:
            print(f"  · {r['name']:<12} {r['msg']}")

    report = os.path.join("out", f"batch_{stamp()}.json")
    with open(report, "w", encoding="utf-8") as f:
        json.dump({"time": now().strftime("%Y-%m-%d %H:%M:%S"), "host": cfg["host"],
                   "dry_run": a.dry_run, "status_only": a.status,
                   "summary": {"ok": len(ok), "skip": len(skip), "fail": len(fail)},
                   "results": results}, f, ensure_ascii=False, indent=2)
    print("-" * 66)
    print(f"报告: {report}")
    print(f"日志: {hq.LOG_PATH}")
    sys.exit(0 if not fail else 1)


if __name__ == "__main__":
    main()
