#!/usr/bin/env bash
# 强制更新 —— 版本号没变/一直提示旧问题时跑这个
# 它会把旧容器、旧镜像、构建缓存全部清掉，从零构建一次
#
#   bash 强制更新.sh
set -u
cd "$(dirname "$0")" || exit 1
F=docker-compose.lan.yml

echo "=============================================="
echo " 强制更新"
echo "=============================================="

echo
echo "[0/6] 宿主机上的文件是什么版本"
if [ -f web/server.py ]; then
  grep -m1 '^VERSION' web/server.py || echo "  ✗ 读不到 web/server.py"
else
  echo "  ✗ 当前目录没有 web/server.py —— 你不在项目目录里"
  echo "    应该 cd 到放 docker-compose.lan.yml 的那个目录"
  exit 1
fi
if [ -f web/index.html ]; then
  grep -m1 "FRONT_VERSION" web/index.html | head -1
fi

echo
echo "[1/6] 停掉并删除旧容器"
docker compose -f "$F" down 2>/dev/null || docker stop hqhs-eval 2>/dev/null && docker rm -f hqhs-eval 2>/dev/null

echo
echo "[2/6] 删掉所有 hqhs-eval 镜像"
OLD=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^hqhs-eval' || true)
if [ -n "$OLD" ]; then
  echo "$OLD" | while read -r img; do
    echo "  删除 $img"
    docker rmi -f "$img" 2>/dev/null || true
  done
else
  echo "  没有旧镜像"
fi

echo
echo "[3/6] 清构建缓存"
docker builder prune -f 2>/dev/null | tail -1

echo
echo "[4/6] 从零构建（--no-cache）"
docker compose -f "$F" build --no-cache || { echo "  ✗ 构建失败，看上面的报错"; exit 1; }

echo
echo "[5/6] 启动容器"
docker compose -f "$F" up -d --force-recreate || { echo "  ✗ 启动失败"; exit 1; }

echo
echo "[6/6] 验证容器里的版本"
sleep 3
V=$(docker exec hqhs-eval grep -m1 '^VERSION' /app/web/server.py 2>/dev/null | tr -d '\r')
echo "  容器内: ${V:-读不到，检查容器名}"

echo
echo "=============================================="
if echo "$V" | grep -q '5\.'; then
  echo " ✓ 完成。刷新浏览器（Ctrl+F5），标题旁应该显示新版本"
else
  echo " ✗ 版本还是不对，把上面全部输出发给我"
fi
echo "=============================================="
