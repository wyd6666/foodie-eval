#!/usr/bin/env bash
# 双击或执行这一行就行：./一键评价.sh
cd "$(dirname "$0")" || exit 1
exec python3 scripts/onekey.py "$@"
