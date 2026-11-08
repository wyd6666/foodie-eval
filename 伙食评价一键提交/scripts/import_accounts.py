#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_accounts.py — 把「账号=密码=姓名」的 txt / CSV / Excel 导出文本转成 accounts.json

支持的输入格式（自动识别，也可以用 --format 指定）:
    370101199001011234=Passw0rd.=张三
    370101199001011234,Passw0rd.,张三
    370101199001011234  Passw0rd.  张三
    张三,370101199001011234,Passw0rd.        （--format name-first）

用法:
    python scripts/import_accounts.py 账号密码.txt
    python scripts/import_accounts.py 名单.csv -o accounts.json
    python scripts/import_accounts.py 名单.txt --format name-first
    python scripts/import_accounts.py 名单.txt --check      # 顺便逐个登录验证密码
"""
import argparse, importlib.util, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _ok(user, pwd):
    """确认这一行真的像「账号 + 密码」，而不是把说明文档里的某句话当成账号。
    典型误判：'1. 双击 win\\7-加人.bat' 会被切成三段。"""
    if not user or not pwd:
        return False
    if len(user) < 4 or len(user) > 40:      # 「双击」「1.」这类直接排除
        return False
    if any(ch.isspace() for ch in user):
        return False
    if user.endswith((".", "。", "：", ":", "、")):   # 序号、句尾
        return False
    if re.search(r"[\u4e00-\u9fff]", user):           # 账号不会含中文，这是文档句子的特征
        return False
    if "：" in pwd or pwd in ("账号", "密码", "姓名"):   # 同上
        return False
    if len(pwd) < 1 or len(pwd) > 64:
        return False
    return True


def mask(s):
    """密码打码：短密码也要盖住大部分"""
    n = len(s)
    if n <= 1:
        return "*"
    if n <= 4:
        return s[0] + "*" * (n - 1)
    return s[:2] + "*" * (n - 2)


SKIP_FILES = {"start_here.txt", "readme.md", "readme.txt", "license", "changelog.md",
              "使用教程.md", "技术说明.md", "部署到1panel.md", "部署到halo.md",
              "dockerfile", "docker-compose.yml", "docker-compose.lan.yml"}


def looks_like_roster(rows):
    """判断解析出来的这批东西是不是真名单。
    真名单的账号基本都是纯数字（身份证/手机号/工号）；
    说明文档被误切出来的"账号"多半是中文词。"""
    if not rows:
        return False
    numeric = sum(1 for r in rows if re.fullmatch(r"\d{8,20}", r.get("userName", "")))
    return numeric / len(rows) >= 0.5


def parse_line(line, fmt=None):
    if line is None:
        return None
    if len(line) > 1000:          # 单行超过 1000 字符肯定不是正常名单，跳过防止卡顿
        return None
    line = line.strip().replace("\ufeff", "")
    # Excel / 微信导出的名单常带引号。只在"成对引号包裹字段"时处理，
    # 不能无脑 strip('"')，否则密码本身带引号会被吃掉。
    if line.count('"') >= 2:
        line = re.sub(r'"\s*([,;=\t])\s*"', r"\1", line)
        if line.startswith('"') and line.endswith('"') and line.count('"') == 2:
            line = line[1:-1]
    line = line.strip("，、 \t")
    if not line or line.startswith("#"):
        return None
    def looks_id(s):
        # 身份证 18 位、手机号 11 位、工号常见 6~12 位，统一按「8~20 位纯数字」认
        return bool(re.fullmatch(r"\d{8,20}", s))

    def looks_num(s):
        return bool(re.fullmatch(r"\d{8,20}", s))

    # 空格分隔：靠「哪个 token 是身份证号」来定位，姓名里带空格也不怕
    if not re.search(r"[=,;\t]", line):
        tokens = [t for t in re.split(r"\s+", line) if t]
        id_idx = next((i for i, t in enumerate(tokens) if looks_id(t)), None)
        if id_idx is not None:
            name = "".join(tokens[:id_idx])
            user = tokens[id_idx]
            pwd = tokens[id_idx + 1] if len(tokens) > id_idx + 1 else ""
            if not name and len(tokens) > id_idx + 2:
                name = tokens[id_idx + 2]      # 「账号 密码 姓名」这种顺序
        elif len(tokens) >= 3 and looks_num(tokens[0]) and not looks_num(tokens[1]):
            # 账号 密码 姓名  （账号是数字，第二个不是数字）
            user, pwd, name = tokens[0], tokens[1], tokens[2]
        elif len(tokens) >= 3:
            name, user, pwd = tokens[0], tokens[1], tokens[2]
        elif len(tokens) == 2:
            user, pwd, name = tokens[0], tokens[1], ""
        else:
            return None
        name = re.sub(r"\s+", "", name) or user[-6:]
        return {"name": name, "userName": user, "passWord": pwd} if _ok(user, pwd) else None

    # = , ; 制表符分隔
    parts = [p.strip() for p in re.split(r"[=,;\t]", line) if p and p.strip()]
    if len(parts) < 2:
        return None
    if fmt == "name-first" or (len(parts) >= 3 and not looks_id(parts[0]) and looks_id(parts[1])):
        name, user, pwd = (parts + ["", ""])[:3]
    else:
        user, pwd = parts[0], parts[1]
        name = parts[2] if len(parts) >= 3 else ""
    name = re.sub(r"\s+", "", name) or user[-6:]
    return {"name": name, "userName": user, "passWord": pwd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="txt / csv 文件")
    ap.add_argument("-o", "--out", default="accounts.json")
    ap.add_argument("--format", choices=["account-first", "name-first"], default=None)
    ap.add_argument("--check", action="store_true", help="逐个登录验证（需要 eval_config.json 里有 host）")
    a = ap.parse_args()

    if not os.path.exists(a.source):
        sys.exit(f"[!] 找不到 {a.source}")

    rows, skipped = [], []
    with open(a.source, encoding="utf-8-sig", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if re.match(r"^\s*(name|姓名)\s*[,=]", line, re.I):
                continue                                   # 表头
            item = parse_line(line, a.format)
            if item and item["userName"] and item["passWord"]:
                rows.append(item)
            elif line.strip():
                skipped.append((i, line.strip()))

    # 去重（同一账号只保留一次）
    seen, uniq = set(), []
    for r in rows:
        if r["userName"] in seen:
            continue
        seen.add(r["userName"]); uniq.append(r)
    rows = uniq

    if not rows:
        sys.exit("[!] 一行都没解析出来，检查分隔符或加 --format name-first")

    json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[✓] {len(rows)} 个账号 -> {a.out}")
    for r in rows:
        print(f"    {r['name']:<6} {r['userName']}  {mask(r['passWord'])}")
    if skipped:
        print(f"[!] 跳过 {len(skipped)} 行（格式不对）:")
        for i, l in skipped[:5]:
            print(f"    第{i}行: {l[:60]}")

    if a.check:
        spec = importlib.util.spec_from_file_location("hq", os.path.join(HERE, "hqhs_eval.py"))
        hq = importlib.util.module_from_spec(spec); spec.loader.exec_module(hq)
        hq.LOG_PATH = None
        cfg = hq.load_cfg("eval_config.json")
        if not cfg.get("host"):
            sys.exit("[!] --check 需要 eval_config.json 里先填 host")
        print(f"\n[验证] 登录 {cfg['host']} ...")
        bad = []
        for r in rows:
            try:
                c = hq.Client(cfg["host"], scheme=cfg.get("scheme", "http"))
                c.ensure_scheme()
                hq.login(c, r["userName"], r["passWord"])
                print(f"    ✓ {r['name']:<6} {r['userName']:<20} {mask(r['passWord']):<12} "
                      f"{(c.user or {}).get('dept_name')}")
            except Exception as e:
                msg = str(e).split(" (code=")[0]
                print(f"    ✗ {r['name']:<6} {r['userName']:<20} {mask(r['passWord']):<12} {msg}")
                bad.append((r["name"], r["userName"], msg))
        print(f"\n验证结果: 通过 {len(rows) - len(bad)} / {len(rows)}")
        if bad:
            if len(bad) == len(rows) and len(rows) > 1:
                print("\n[!] 一个都没过，八成不是密码问题，而是名单被解析错了。")
                print("    看看上面每行中间那列「账号」是不是被填成了密码/姓名。")
                print("    支持的写法：")
                print("      姓名 账号 密码        （账号是数字，中间用空格）")
                print("      账号=密码=姓名")
                print("      账号,密码,姓名")
                print("    如果是其他格式，用 --format name-first 指定姓名在最前。")
            sys.exit(1)


if __name__ == "__main__":
    main()
