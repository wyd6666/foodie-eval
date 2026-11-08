#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manage_accounts.py — 名单管理：加人 / 删人 / 看名单 / 验密码

不用手工编辑 JSON，也不用重新导入整份名单。每次改动自动备份，且按账号去重。

常用:
  python scripts/manage_accounts.py add 张三 370101199001011234 Passw0rd.
  python scripts/manage_accounts.py add --from 新人.txt          # 追加一批
  python scripts/manage_accounts.py list                          # 看现在有哪些人
  python scripts/manage_accounts.py list --check                  # 顺便登录验证
  python scripts/manage_accounts.py del 张三
  python scripts/manage_accounts.py del 370101199001011234,李四   # 批量删
  python scripts/manage_accounts.py add                                # 交互式一个个加

选项:
  -f, --file     名单文件，默认 accounts.json
  --check        加/列完立刻登录验证（需要 eval_config.json 里有 host）
  --quiet        少打印
"""
import argparse, json, os, shutil, sys, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

DEFAULT = "accounts.json"


# ---------------- 读写 ----------------
def load(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"[!] {path} 不是合法 JSON（第 {e.lineno} 行附近）。\n"
                 f"    可以删掉它重新跑导入，或看看是不是多了/少了逗号。")
    if isinstance(data, dict):
        data = data.get("accounts", [])
    return [r for r in data if isinstance(r, dict)]


def save(rows, path):
    """原子写 + 自动备份，避免手滑把名单写没"""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def mask(s):
    n = len(s)
    if n <= 1:
        return "*"
    if n <= 4:
        return s[0] + "*" * (n - 1)
    return s[:2] + "*" * (n - 2)


def norm_name(x):
    return re.sub(r"\s+", "", x or "")


def merge(rows, new_rows, quiet=False):
    """按 userName 去重：已存在就更新姓名/密码，不会产生重复条目"""
    index = {r.get("userName"): i for i, r in enumerate(rows)}
    added, updated = [], []
    for nr in new_rows:
        u = str(nr.get("userName") or "").strip()
        if not u:
            continue
        nr["name"] = norm_name(nr.get("name")) or u[-6:]
        nr["userName"] = u
        nr["passWord"] = str(nr.get("passWord") or "")
        if u in index:
            old = rows[index[u]]
            if old.get("passWord") != nr["passWord"] or old.get("name") != nr["name"]:
                old.update(nr)
                updated.append(nr)
        else:
            index[u] = len(rows)
            rows.append(nr)
            added.append(nr)
    if not quiet:
        for r in added:
            print(f"    + {r['name']:<6} {r['userName']}")
        for r in updated:
            print(f"    ~ {r['name']:<6} {r['userName']}  (已存在，更新了信息)")
    return added, updated


# ---------------- 子命令 ----------------
def cmd_add(a):
    rows = load(a.file)
    new_rows = []

    if a.from_file:
        spec = importlib_spec()
        imp = spec
        with open(a.from_file, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                item = imp.parse_line(line)
                if item:
                    new_rows.append(item)
        if not new_rows:
            sys.exit(f"[!] {a.from_file} 里没解析出账号")
    elif a.args:
        if len(a.args) < 3:
            sys.exit("用法: add 姓名 账号 密码   （或者 add --from 文件）")
        new_rows.append({"name": norm_name(a.args[0]), "userName": a.args[1].strip(),
                         "passWord": a.args[2]})
    else:
        # 交互式：一行一个，直接回车结束
        print("逐个输入，格式：姓名 账号 密码   （直接回车结束）")
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                break
            parts = line.split()
            if len(parts) < 3:
                print("  格式不对，要三段：姓名 账号 密码")
                continue
            new_rows.append({"name": norm_name(parts[0]), "userName": parts[1],
                             "passWord": parts[2]})

    if not new_rows:
        sys.exit("[!] 没有要添加的内容")

    added, updated = merge(rows, new_rows, a.quiet)
    save(rows, a.file)
    print(f"[✓] 新增 {len(added)} 人，更新 {len(updated)} 人，现在共 {len(rows)} 人 -> {a.file}")
    print(f"    备份: {a.file}.bak")
    if a.check:
        do_check(rows, a)


def _load(mod_name, filename):
    import importlib.util
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(HERE, filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def importlib_spec():
    return _load("imp", "import_accounts.py")


def cmd_del(a):
    rows = load(a.file)
    keys = {norm_name(k) for k in ",".join(a.keys).split(",") if k.strip()}
    if not keys:
        sys.exit("用法: del 姓名或账号 [更多...]")
    keep, gone = [], []
    for r in rows:
        if r.get("name") in keys or r.get("userName") in keys:
            gone.append(r)
        else:
            keep.append(r)
    if not gone:
        sys.exit(f"[!] 名单里没有: {', '.join(sorted(keys))}")
    save(keep, a.file)
    for r in gone:
        print(f"    - {r.get('name'):<6} {r.get('userName')}")
    print(f"[✓] 删除 {len(gone)} 人，现在共 {len(keep)} 人 -> {a.file}")
    print(f"    备份: {a.file}.bak（删错了直接把它复制回去）")


def cmd_list(a):
    rows = load(a.file)
    if not rows:
        sys.exit(f"名单是空的：{a.file}")
    print(f"{a.file}: 共 {len(rows)} 人")
    print(f"  {'序号':<4}{'姓名':<8}{'账号':<22}{'密码'}")
    for i, r in enumerate(rows, 1):
        print(f"  {i:<4}{r.get('name',''):<8}{r.get('userName',''):<22}{mask(str(r.get('passWord') or ''))}")
    if a.check:
        do_check(rows, a)


def do_check(rows, a):
    hqe = _load("hqhs_eval", "hqhs_eval.py")
    hqe.LOG_PATH = None

    cfg = hqe.load_cfg(os.path.join(ROOT, "eval_config.json"))
    host = cfg.get("host")
    if (not host) or str(host).startswith("[") or "填" in str(host):
        sys.exit("[!] --check 需要先在 eval_config.json 里填 host")
    print(f"\n[验证] 登录 {host} ...")
    bad = 0
    for r in rows:
        try:
            c = hqe.Client(host, scheme=cfg.get("scheme", "http"))
            c.ensure_scheme()
            hqe.login(c, r["userName"], r["passWord"])
            print(f"    ✓ {r.get('name',''):<6} {(c.user or {}).get('dept_name')}")
        except Exception as e:
            bad += 1
            print(f"    ✗ {r.get('name',''):<6} {str(e).split(' (code=')[0]}")
    print(f"\n验证结果: 通过 {len(rows) - bad} / {len(rows)}")


def main():
    ap = argparse.ArgumentParser(description="名单管理")
    ap.add_argument("cmd", choices=["add", "addfile", "del", "list", "check"])
    ap.add_argument("args", nargs="*", help="add: 姓名 账号 密码 / del: 姓名或账号")
    ap.add_argument("-f", "--file", default=DEFAULT)
    ap.add_argument("--from", dest="from_file", help="addfile: 从 txt/csv 追加")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.cmd == "add":
        cmd_add(a)
    elif a.cmd == "addfile":
        if not a.args:
            sys.exit("用法: addfile 新人.txt")
        a.from_file = a.args[0]
        cmd_add(a)
    elif a.cmd == "del":
        a.keys = a.args
        cmd_del(a)
    elif a.cmd == "list":
        cmd_list(a)
    elif a.cmd == "check":
        do_check(load(a.file), a)


if __name__ == "__main__":
    main()
