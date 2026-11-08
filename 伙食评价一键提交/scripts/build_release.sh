#!/usr/bin/env bash
# build_release.sh — 把「一键评价」这一套打成一个可分发的 zip
#
#   bash scripts/build_release.sh
#   -> release/伙食评价一键提交-v1.0.zip
#
# 包里只放脚本 + 教程 + 模板，不放：真实名单、账号密码、out/、.venv/、tools/、apk/
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER="${1:-v1.0}"
NAME="伙食评价一键提交"
REL="release/$NAME"
ZIP="release/${NAME}-${VER}.zip"

mkdir -p release
rm -rf "$REL"                       # 只清上一次的解压目录，历史 zip 保留
mkdir -p "$REL"/{scripts,win,examples,tests,web}

# ---- 源码快照：每次打包前留一份，方便回滚 ----
SVER=$(grep -m1 '^VERSION' web/server.py 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "")
if [ -n "$SVER" ]; then
  SNAP="versions/v$SVER"
  if [ -d "$SNAP" ]; then
    echo "快照 $SNAP 已存在，保留原样（不覆盖历史）"
  else
    mkdir -p "$SNAP"
    cp -r web scripts win tests examples "$SNAP"/ 2>/dev/null
    rm -rf "$SNAP"/tests/fixtures "$SNAP"/tests/__pycache__ "$SNAP"/scripts/__pycache__ "$SNAP"/web/__pycache__ 2>/dev/null
    cp Dockerfile docker-compose.lan.yml .dockerignore .env.example run.sh \
       使用教程.md 部署到1Panel.md hqhs-README.md START_HERE.txt \
       accounts.example.json accounts.example.csv eval_config.json \
       一键评价.sh 一键评价.bat 网页版.sh 网页版.bat 自检.sh 自检.bat \
       重建.sh 重建.bat 强制更新.sh 准备镜像.sh 测试镜像源.sh \
       "$SNAP"/ 2>/dev/null
    printf '%s\n' "$SNAP" > "$SNAP/.snapshot-info"
    echo "  ✓ 源码快照: $SNAP" >> "$SNAP/.snapshot-info"
    echo "    时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$SNAP/.snapshot-info"
    echo "    版本: $SVER" >> "$SNAP/.snapshot-info"
    echo "已存源码快照 $SNAP"
  fi
fi

cp run.sh 部署手册.md 使用教程.md 部署到1Panel.md hqhs-README.md 一键评价.sh 一键评价.bat 网页版.sh 网页版.bat 自检.sh 自检.bat "$REL"/
cp web/*.py web/*.html web/*.txt "$REL/web/" 2>/dev/null
cp Dockerfile docker-compose.lan.yml .dockerignore .env.example 测试镜像源.sh 准备镜像.sh 重建.sh 重建.bat 强制更新.sh 恢复版本.sh "$REL"/ 2>/dev/null
cp scripts/*.py scripts/*.sh scripts/*.js "$REL/scripts/" 2>/dev/null
cp win/*.bat "$REL/win/" 2>/dev/null
cp tests/mock_hqhs.py "$REL/tests/" 2>/dev/null
cp accounts.example.json accounts.example.csv "$REL"/ 2>/dev/null
chmod +x "$REL"/scripts/*.sh "$REL/run.sh" 2>/dev/null

# 脱敏的配置模板（绝对不能把真实 host / 密码打进去）
cat > "$REL/eval_config.json" <<'EOF'
{
  "_说明": "只改 host：填你手机 App 登录页里那个服务器地址，不要带 http:// 也不要带 /api/",
  "scheme": "http",
  "host": "[填服务器地址 例如 sd.example.gov.cn 或 10.1.2.3:8080]",
  "presets": [],
  "_presets说明": "把常用地址填进 presets 数组，网页上会出现可点击、可复制的胶囊。例：sd.example.gov.cn",
  "userName": "",
  "passWord": "",
  "strategy": "max",
  "timeout": 15,
  "log_dir": "out",

  "_动态码说明": "填了 totp_secret 就改用手机动态码登录（30 秒一变，6 位数字）。留空则用上面的静态密码",
  "totp_secret": "",
  "_动态码生成": "命令行跑 python web/server.py --gen-totp，会给你密钥和导入链接",
  "totp_window": 1,
  "_auth_mode说明": "totp=只认动态码（默认）；password=只认静态密码；both=两个都认",
  "auth_mode": ""
}
EOF

# 示例报告：取最近一次真实运行，账号打码
if ls out/batch_*.json >/dev/null 2>&1; then
  "$ROOT/.venv/bin/python" - "$REL/examples/batch_report_sample.json" <<'PY'
import glob, json, re, sys
src = sorted(glob.glob("out/batch_*.json"))[-1]
d = json.load(open(src, encoding="utf-8"))
d["host"] = "sd.example.gov.cn"
for r in d["results"]:
    r["userName"] = "3702**********1234"
    if r.get("name"):
        r["name"] = r["name"][0] + "*"
    dept = r.get("dept") or ""
    if dept:
        r["dept"] = re.sub(r"^..市", "XX市", dept) if len(dept) > 3 else "XX站"
json.dump(d, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("示例报告 <-", src, "(已脱敏)")
PY
fi

cat > "$REL/START_HERE.txt" <<'EOF'
伙食满意度测评 · 一键提交
==========================

最省事的用法
------------
喜欢点鼠标：  双击  网页版.bat        浏览器里粘贴名单，点两下就交完
喜欢命令行：  Windows 双击 一键评价.bat / Mac 执行 ./一键评价.sh

它会自动装依赖、找名单、先预演一遍，然后等你按一下回车才真的提交。
第一次运行会问一次服务器地址（手机上 App 登录页里那个地址），问完就记住了。

重复提交会被自动挡住：今天已经交过的人，再点一次也不会重复交。


第一次用，建议这样走一遍
------------------------
  1. 把名单放到这个文件夹，一行一个人：姓名 账号 密码
  2. 双击 一键评价.bat
  3. 第一次会让你输一次服务器地址
  4. 看到「预演结果：能交 X 人」，按回车
  5. 看到「全部搞定」就好了


网页版长什么样
--------------
  双击 网页版.bat -> 浏览器自动打开 http://127.0.0.1:8080
  ① 填服务器地址（一次就行）
  ② 把名单 txt 拖进去，或直接粘贴
  ③ 点「先预演（不提交）」看结果，再点「直接提交」
  ④ 下面实时冒出每人的结果
  今天交过的人会自动跳过，不会重复交

要部署给别人用？
----------------
  看 部署手册.md —— 四种方式（Windows 双击 / Mac 命令行 /
  Docker / 服务器直接跑 Python）全在里面，按你的情况挑一种。

  只自己一台电脑用：双击 网页版.bat 就行，不用看文档。


以后日常
--------
  交评价：        双击 一键评价.bat（或 ./一键评价.sh），按回车
  加人：          双击 win-加人.bat
  看名单：        双击 win\8-看名单.bat
  删人：          双击 win\9-删人.bat
  只用手机不想开电脑：看 使用教程.md 第 9 章


想分步控制（高级）
------------------
  bash run.sh batch -a accounts.json --dry-run   # 只预演
  bash run.sh batch -a accounts.json             # 提交
  bash run.sh batch -a accounts.json --status    # 查记录
  完整清单见 使用教程.md 附录


文档
----
  使用教程.md   ← 普通用户看这个
  技术说明.md   ← 接口是怎么逆出来的、改包怎么做的

安全提醒：账号密码.txt 和 accounts.json 都是明文，用完请删除或妥善保管。
本包内不含任何真实账号。
EOF
# 打包（排除掉可能被误创建的各种缓存）
cd release
if command -v zip >/dev/null 2>&1; then
  zip -qr "${NAME}-${VER}.zip" "$NAME" -x "*.pyc" -x "*__pycache__*" -x "*.log"
else
  "$ROOT/.venv/bin/python" - "$NAME" "${NAME}-${VER}.zip" <<'PY'
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith((".pyc", ".log")):
                continue
            p = os.path.join(root, f)
            z.write(p, p)
PY
fi
cd "$ROOT"

echo
echo "================ 打包完成 ================"
echo "zip : release/${NAME}-${VER}.zip"
echo "大小: $(du -h "release/${NAME}-${VER}.zip" | cut -f1)"
echo "文件: $(find "$REL" -type f | wc -l) 个"
echo
echo "内容:"
find "$REL" -type f | sed "s|$REL/|  |" | sort
echo
echo "自检: 确认包里没有真实凭据 ——"
if grep -rl "TQ119@1\.\|TQ129@1\.\|sd\.ysbz\.119" "$REL" \
     --exclude=build_release.sh 2>/dev/null | head -5; then
  echo "  ⚠ 上面这些文件里出现了真实域名/密码，请检查！"
else
  echo "  ✓ 没有检出真实服务器地址或密码"
fi
