#!/usr/bin/env bash
# 把源码恢复到某个历史版本
#
#   bash 恢复版本.sh            # 看有哪些版本
#   bash 恢复版本.sh v5.3.0     # 恢复到 v5.3.0
set -u
cd "$(dirname "$0")" || exit 1

if [ $# -eq 0 ]; then
  echo "现有版本快照："
  echo
  if [ -d versions ]; then
    for d in $(ls -1 versions 2>/dev/null | sort -V); do
      ver=$(grep -m1 '版本:' "versions/$d/.snapshot-info" 2>/dev/null | sed 's/.*版本: //')
      ts=$(grep -m1 '时间:' "versions/$d/.snapshot-info" 2>/dev/null | sed 's/.*时间: //')
      printf "  %-12s %s  %s\n" "$d" "${ver:-?}" "${ts:-}"
    done
  else
    echo "  （还没有任何快照，下次打包时会自动生成）"
  fi
  echo
  echo "恢复某个版本： bash 恢复版本.sh v5.3.0"
  exit 0
fi

V="$1"
[ -d "versions/$V" ] || { echo "没有 versions/$V"; echo; bash "$0"; exit 1; }

echo "把当前源码备份到 /tmp/hqhs-before-restore"
mkdir -p /tmp/hqhs-before-restore
cp -r web scripts win examples /tmp/hqhs-before-restore/ 2>/dev/null

echo "从 versions/$V 恢复 …"
cp -r "versions/$V"/web "versions/$V"/scripts . 2>/dev/null
[ -d "versions/$V/win" ] && cp -r "versions/$V"/win .
[ -d "versions/$V/examples" ] && cp -r "versions/$V"/examples .
for f in Dockerfile docker-compose.lan.yml run.sh 使用教程.md 部署到1Panel.md \
         hqhs-README.md eval_config.json 一键评价.sh 网页版.sh 自检.sh \
         重建.sh 强制更新.sh 准备镜像.sh 测试镜像源.sh; do
  [ -f "versions/$V/$f" ] && cp "versions/$V/$f" .
done

echo "✓ 已恢复到 $V"
grep -m1 '^VERSION' web/server.py
echo
echo "要重新打包并部署，跑： bash 重建.sh"
