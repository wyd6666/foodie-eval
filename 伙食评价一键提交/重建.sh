#!/usr/bin/env bash
# 一键重建 —— 做对这三件事：清缓存构建、强制重建容器、验证版本
#
#   bash 重建.sh                     # 默认用 docker-compose.lan.yml
#   bash 重建.sh docker-compose.yml  # 指定编排文件
set -u
cd "$(dirname "$0")" || exit 1

FILE="${1:-docker-compose.lan.yml}"
[[ -f "$FILE" ]] || { echo "找不到 $FILE"; exit 1; }

echo "=============================================="
echo " 用 $FILE 重建"
echo "=============================================="

echo
echo "[1/3] 构建镜像（--no-cache，不用旧缓存）"
docker compose -f "$FILE" build --no-cache || { echo "✗ 构建失败，看上面的报错"; exit 1; }

echo
echo "[2/3] 重建容器"
docker compose -f "$FILE" up -d --force-recreate || { echo "✗ 启动失败"; exit 1; }

echo
echo "[3/3] 验证容器里的版本"
sleep 2
docker exec hqhs-eval grep '^VERSION' /app/web/server.py 2>/dev/null \
  || echo "  （读不到，检查容器名是不是 hqhs-eval）"

echo
echo "=============================================="
echo " 完成。浏览器打开页面，标题旁应该显示新版本号"
echo "=============================================="
