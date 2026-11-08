#!/usr/bin/env bash
# run.sh — 命令行入口（网页版以外的用法）
#
#   bash run.sh hqhs    [--dry-run|--status]      单账号提交 / 查状态
#   bash run.sh batch   [-a accounts.json]        多账号批量（--dry-run 预演）
#   bash run.sh import  名单.txt                  导入「姓名 账号 密码」名单
#   bash run.sh add     姓名 账号 密码            加一个人（自动去重+备份）
#   bash run.sh addfile 新人.txt                  从 txt 追加一批人
#   bash run.sh list    [--check]                 看名单（密码打码，--check 验密码）
#   bash run.sh del     账号                      删一个人
#   bash run.sh web     [--port 8080]             启动网页版
#   bash run.sh check                             环境自检
#
# 日常用不到这些 —— 双击 一键评价.bat / 网页版.bat 就行。
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
HERE="$(pwd)"
SCRIPTS="$HERE/scripts"

cmd="${1:-help}"; shift || true

case "$cmd" in
  hqhs)    exec $PY "$SCRIPTS/hqhs_eval.py" "$@" ;;
  batch)   exec $PY "$SCRIPTS/hqhs_batch.py" "$@" ;;
  import)  exec $PY "$SCRIPTS/import_accounts.py" "$@" ;;
  add)     exec $PY "$SCRIPTS/manage_accounts.py" add "$@" ;;
  addfile) exec $PY "$SCRIPTS/manage_accounts.py" addfile "$@" ;;
  list)    exec $PY "$SCRIPTS/manage_accounts.py" list "$@" ;;
  del)     exec $PY "$SCRIPTS/manage_accounts.py" del "$@" ;;
  check)   exec $PY "$SCRIPTS/selfcheck.py" "$@" ;;
  web)     exec $PY "$HERE/web/server.py" "$@" ;;

  help|-h|--help)
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    ;;

  *)
    echo "不认识的命令: $cmd"
    echo
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
