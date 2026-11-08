#!/usr/bin/env bash
# 网页版：浏览器里粘贴名单，点一下自动评价
cd "$(dirname "$0")" || exit 1
exec python3 web/server.py "$@"
