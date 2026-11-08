#!/usr/bin/env bash
# 预拉基础镜像并打上 python:3.11-slim 的标签
# 这样 docker build 时直接用本地镜像，不用再联网拉，构建快很多
#
#   bash 准备镜像.sh
set -u

TARGET="python:3.11-slim"
SOURCES=(
  "docker.m.daocloud.io/library/python:3.11-slim"
  "docker.1ms.run/library/python:3.11-slim"
  "docker.1panel.live/library/python:3.11-slim"
  "hub.rat.dev/library/python:3.11-slim"
  "python:3.11-slim"
)

echo "=============================================="
echo " 准备基础镜像 $TARGET"
echo "=============================================="

# 已经有就不用再拉
if docker image inspect "$TARGET" >/dev/null 2>&1; then
  echo "✓ 本地已经有 $TARGET，跳过"
  docker images "$TARGET"
  exit 0
fi

for src in "${SOURCES[@]}"; do
  echo
  echo "→ 尝试: $src"
  if timeout 300 docker pull "$src"; then
    docker tag "$src" "$TARGET"
    echo
    echo "✓ 完成，已命名为 $TARGET（来自 $src）"
    echo "  现在可以直接: docker compose build --no-cache"
    exit 0
  fi
  echo "  ✗ 这个源不行，换下一个"
done

echo
echo "=============================================="
echo "✗ 所有源都拉不动"
echo
echo "两个选择："
echo "  1) 配 Docker 镜像加速器后重试（见 部署到1Panel.md）"
echo "  2) 别用 Docker 了，直接用 Python 跑："
echo "       python3 -m venv .venv"
echo "       .venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests"
echo "       .venv/bin/python web/server.py --host 0.0.0.0 --port 8080 --password 你的密码"
echo "     PyPI 走清华源国内很快，比拉 Docker 镜像稳"
echo "=============================================="
exit 1
