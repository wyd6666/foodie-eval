#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
onekey.py — 一条命令/一次双击，把能自动的都自动掉

它会依次干这些事，中途只在「必须你决定」的时候才停下来问你：
  1. 检查依赖，缺就自动装
  2. 找服务器地址（配置里没有就问一次，然后记住）
  3. 找名单（accounts.json / 账号密码.txt / *.csv，自动导入）
  4. 先预演一遍（不会提交），告诉你谁能交、谁今天已经交过、谁密码错
  5. 你按一下回车，才真的提交

用法:
  python scripts/onekey.py            # 正常用：预演 -> 问一句 -> 提交
  python scripts/onekey.py --yes      # 全自动，不问（给定时任务用）
  python scripts/onekey.py --dry      # 只预演，不提交
  python scripts/onekey.py --host 10.1.2.3:8080   # 临时指定服务器
"""
import argparse, glob, importlib.util, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BATCH = os.path.join(HERE, "hqhs_batch.py")
CONFIG = os.path.join(ROOT, "eval_config.json")
LAST_HOST = os.path.join(ROOT, "out", ".last_host")
REQ = ("requests", "cryptography", "yaml")

def is_placeholder(x):
    """空串 / 以 [ 开头 / 含「填」字，都当成还没填。
    注意不能用 startswith("") —— 那样任何值都为真。"""
    v = str(x or "").strip()
    return (not v) or v.startswith("[") or "填" in v


def say(msg=""):
    print(msg, flush=True)


def head(title):
    say("=" * 46)
    say(" " + title)
    say("=" * 46)


# ---------------- 1. 依赖 ----------------
def ensure_deps(auto=True):
    missing = []
    for m in REQ:
        try:
            __import__(m)
        except ImportError:
            missing.append("pyyaml" if m == "yaml" else m)
    if not missing:
        say("✓ 依赖检查通过")
        return True
    say(f"! 缺依赖: {', '.join(missing)}")
    if not auto:
        say(f"  请执行: pip install {' '.join(missing)}")
        return False
    say("  正在自动安装（用清华镜像，约十几秒）...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", *missing],
                       check=True)
    except Exception as e:
        say(f"  自动安装失败: {e}")
        say(f"  请手动执行: pip install {' '.join(missing)}")
        return False
    say("✓ 依赖安装完成")
    return True


# ---------------- 2. 服务器地址 ----------------
def _load_cfg():
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cfg(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def resolve_host(cli_host=None):
    cfg = _load_cfg()
    for cand in (cli_host, cfg.get("host")):
        if not is_placeholder(cand):
            host = str(cand).strip()
            os.makedirs(os.path.dirname(LAST_HOST), exist_ok=True)
            with open(LAST_HOST, "w", encoding="utf-8") as f:
                f.write(host)
            if cfg.get("host") != host:
                cfg["host"] = host
                _save_cfg(cfg)
            say(f"✓ 服务器: {host}")
            return host

    if os.path.exists(LAST_HOST):
        host = open(LAST_HOST, encoding="utf-8").read().strip()
        if host:
            say(f"✓ 服务器: {host}（上次用的）")
            return host

    say("")
    say("第一次运行，需要填一次服务器地址。")
    say("去手机 App 的登录页看那个地址（登录页上有个设置/IP 的地方，或者问管理员）。")
    say("例如：sd.example.gov.cn  或者  10.1.2.3:8080")
    say("")
    while True:
        try:
            host = input("服务器地址: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        host = host.replace("http://", "").replace("https://", "").rstrip("/")
        if host.endswith("/api"):
            host = host[:-4]
        if host:
            break
        say("  不能是空的，再输一次。")
    cfg["host"] = host
    cfg.setdefault("scheme", "http")
    cfg.setdefault("strategy", "max")
    cfg.setdefault("timeout", 15)
    cfg.setdefault("log_dir", "out")
    _save_cfg(cfg)
    os.makedirs(os.path.dirname(LAST_HOST), exist_ok=True)
    with open(LAST_HOST, "w", encoding="utf-8") as f:
        f.write(host)
    say(f"✓ 服务器: {host}（已记住，下次不用再填）")
    return host


# ---------------- 3. 名单 ----------------
def _accounts_n(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        return len(d) if isinstance(d, list) else len(d.get("accounts", []))
    except Exception:
        return 0


def _import_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def resolve_accounts():
    acc = os.path.join(ROOT, "accounts.json")
    if os.path.exists(acc) and _accounts_n(acc) > 0:
        say(f"✓ 名单: accounts.json（{_accounts_n(acc)} 人）")
        return acc

    imp = _import_module("imp", "import_accounts.py")

    # 自动找 txt / csv 名单
    cands = []
    for pat in ("*.txt", "*.csv"):
        for p in glob.glob(os.path.join(ROOT, pat)):
            base = os.path.basename(p).lower()
            if base in ("requirements.txt",) or base in imp.SKIP_FILES:
                continue
            if "example" in base or "示例" in base:      # 模板文件别当名单用
                continue
            cands.append(p)
    # 名字里带"账号/密码/名单/人员"的优先
    cands.sort(key=lambda p: (0 if any(k in os.path.basename(p) for k in ("账号", "密码", "名单", "人员")) else 1, p))

    for p in cands:
        rows = []
        try:
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    item = imp.parse_line(line)
                    if item and item["userName"] and item["passWord"]:
                        rows.append(item)
        except Exception:
            continue
        if rows and imp.looks_like_roster(rows):
            json.dump(rows, open(acc, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            say(f"✓ 名单: 从 {os.path.basename(p)} 自动导入 {len(rows)} 人 -> accounts.json")
            return acc
        if rows:
            say(f"  跳过 {os.path.basename(p)}：解析出 {len(rows)} 行，但账号不像真账号（可能不是名单文件）")

    say("")
    say("没找到名单。有三种办法（选一种就行）：")
    say("  1) 把一份 txt 放到这个文件夹，一行一个人：姓名 账号 密码")
    say("  2) 双击 win\\7-加人.bat 一个个加")
    say("  3) 直接在下面输入，格式：姓名 账号 密码（输完按回车，直接回车结束）")
    say("")
    rows = []
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        parts = line.split()
        if len(parts) < 3:
            say("  要三段：姓名 账号 密码")
            continue
        rows.append({"name": parts[0], "userName": parts[1], "passWord": parts[2]})
    if not rows:
        say("! 没有名单，退出")
        return None
    json.dump(rows, open(acc, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    say(f"✓ 已保存 {len(rows)} 人到 accounts.json")
    return acc


# ---------------- 4. 跑批量 ----------------
def run_batch(acc, dry=False, status=False, skip_today=True):
    before = set(glob.glob(os.path.join(ROOT, "out", "batch_*.json")))
    cmd = [sys.executable, BATCH, "-a", acc, "--quiet"]
    if skip_today:
        cmd.append("--skip-today")
    if dry:
        cmd.append("--dry-run")
    if status:
        cmd.append("--status")
    rc = subprocess.run(cmd, cwd=ROOT).returncode

    after = sorted(set(glob.glob(os.path.join(ROOT, "out", "batch_*.json"))) - before)
    summary = {}
    if after:
        try:
            summary = json.load(open(after[-1], encoding="utf-8")).get("summary", {})
        except Exception:
            pass
    return summary, rc, (after[-1] if after else None)


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="全自动，不做确认（定时任务用）")
    ap.add_argument("--dry", action="store_true", help="只预演")
    ap.add_argument("--host")
    ap.add_argument("--force", action="store_true",
                    help="忽略「今天已交过」的台账，强制再交一次")
    a = ap.parse_args()

    os.chdir(ROOT)
    head("伙食评价 · 一键提交")

    if not ensure_deps(auto=not a.dry):
        sys.exit(1)

    host = resolve_host(a.host)
    if not host:
        sys.exit("! 没有服务器地址")

    acc = resolve_accounts()
    if not acc:
        sys.exit(1)

    say("")
    say("--- 预演（只登录和算分，不会提交）---")
    if a.force:
        say("! --force：忽略台账，今天已交过的人也会再交一次")
    s1, rc1, _ = run_batch(acc, dry=True, skip_today=not a.force)
    ok, skip, fail = s1.get("ok", 0), s1.get("skip", 0), s1.get("fail", 0)
    say("")
    say(f"预演结果：能交 {ok} 人 | 今天已交 {skip} 人 | 有问题 {fail} 人")

    if ok == 0 and skip > 0:
        say("")
        say("今天这些人都已经交过了，没有要做的。")
        if fail:
            say(f"（另外有 {fail} 个人预演没过，多半是密码错，用 win\\8-看名单.bat 或 "
                f"bash run.sh list --check 查一下）")
        sys.exit(0)
    if ok == 0:
        say("")
        say("没有一个人能交 —— 看上面的报错。密码错了就先用 win\\8-看名单.bat 验一下。")
        sys.exit(1)

    if a.dry:
        say("")
        say("--dry 模式，到此为止。去掉 --dry 就会真的提交。")
        return

    if fail and not a.yes:
        say("")
        say(f"注意：有 {fail} 个人预演没过（多半是密码错），提交时会跳过他们。")
    if not a.yes:
        try:
            input("\n按回车开始提交（Ctrl+C 取消）... ")
        except (EOFError, KeyboardInterrupt):
            say("\n已取消，什么都没提交。")
            return

    say("")
    say("--- 提交中 ---")
    s2, rc2, report = run_batch(acc, dry=False, skip_today=not a.force)
    ok2, skip2, fail2 = s2.get("ok", 0), s2.get("skip", 0), s2.get("fail", 0)

    say("")
    head("完成")
    say(f"交上了 {ok2} 人")
    if skip2:
        say(f"本来就已经交过 {skip2} 人")
    if fail2:
        say(f"没成功 {fail2} 人（原因看上面的 ✗ 行）")
    if report:
        say("")
        say(f"明细记录：{os.path.relpath(report, ROOT)}")
    if not fail2:
        say("")
        say("全部搞定。")


if __name__ == "__main__":
    main()
