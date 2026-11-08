#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selfcheck.py — 一键环境自检。网页打不开、或者报错看不懂时，先跑这个。

用法：
    python scripts/selfcheck.py
    python scripts/selfcheck.py 服务器地址      # 顺便测连通性（可选）

输出的整段内容可以直接发给维护者。
"""
import glob, json, os, platform, sys, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def line(k, v):
    print(f"  {k:<16}{v}")


def main():
    print("=" * 56)
    print(" 伙食评价 · 环境自检")
    print("=" * 56)

    print("\n[1] 运行环境")
    line("Python", sys.version.replace("\n", " "))
    line("可执行文件", sys.executable)
    line("平台", platform.platform())
    line("工作目录", os.getcwd())
    line("项目目录", ROOT)

    print("\n[2] 依赖")
    ok = True
    for name, pkg in (("requests", "requests"), ("cryptography", "cryptography"), ("yaml", "pyyaml")):
        try:
            mod = __import__(name)
            line(pkg, getattr(mod, "__version__", "已安装"))
        except Exception as e:
            ok = False
            line(pkg, f"✗ 未安装 / 导入失败: {type(e).__name__}: {e}")
    if not ok:
        print(f"\n  → 先装依赖:  {sys.executable} -m pip install requests cryptography pyyaml")

    print("\n[3] 核心逻辑（AES 复刻）")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("hq", os.path.join(ROOT, "scripts", "hqhs_eval.py"))
        hq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hq)
        rep = hq.env_report()
        line("cryptography 接口", rep.get("cipher_api", "?"))
        line("AES 自检", rep.get("aes") or "失败")
        got = hq.aes_encrypt("zhangsan")
        expect = "8A482F70744DA1853EDA33EC908B9A04"
        line("与 App 对齐", "✓ 一致" if got == expect else f"✗ 不一致（得到 {got}）")
        if rep.get("problems"):
            for p in rep["problems"]:
                line("问题", p)
    except Exception:
        ok = False
        print("  ✗ 加载核心逻辑失败：")
        print(traceback.format_exc())

    print("\n[4] 服务器连接")
    host = sys.argv[1] if len(sys.argv) > 1 else ""
    if not host:
        cfg_path = os.path.join(ROOT, "eval_config.json")
        if os.path.exists(cfg_path):
            try:
                host = (json.load(open(cfg_path, encoding="utf-8-sig")).get("host") or "")
            except Exception:
                pass
    if host and not str(host).startswith("[") and "填" not in str(host):
        line("配置里的地址", host)
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("hq2", os.path.join(ROOT, "scripts", "hqhs_eval.py"))
            hq2 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hq2)
            c = hq2.Client(host, timeout=8)
            c.ensure_scheme()
            r = c.s.get(c.base, timeout=8, allow_redirects=False)
            line("实际访问", c.base)
            line("HTTP 状态", r.status_code)
            print("  ✓ 能连上" if r.status_code < 500 else "  ! 能连上但返回异常")
        except Exception as e:
            ok = False
            line("连接结果", f"✗ {type(e).__name__}: {e}")
    else:
        line("配置里的地址", "（还没填）")

    print("\n[5] 最近日志里的报错")
    logs = sorted(glob.glob(os.path.join(ROOT, "out", "**", "*.log"), recursive=True), key=os.path.getmtime)[-3:]
    found = False
    for p in logs:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-200:]
        except Exception:
            continue
        errs = [l.rstrip() for l in tail if ("错误" in l or "失败" in l or "Error" in l
                                             or "Traceback" in l or "Exception" in l)]
        if errs:
            found = True
            print(f"  --- {os.path.relpath(p, ROOT)} ---")
            for l in errs[-8:]:
                print("   ", l[:200])
    if not found:
        print("  （最近日志里没有报错）")

    print("\n" + "=" * 56)
    print(" 结论: " + ("✓ 环境正常" if ok else "✗ 上面标 ✗ 的地方就是问题"))
    print(" 把这一整段复制发给维护者即可")
    print("=" * 56)


if __name__ == "__main__":
    main()
