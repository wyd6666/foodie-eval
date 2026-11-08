#!/usr/bin/env bash
# 在服务器上跑这个，看哪个 Docker 镜像源能用（挑最快的那个）
#   bash 测试镜像源.sh
#
# 说明：Docker Registry 的 /v2/ 接口在没有 token 时正常就返回 401，
#      所以 200 / 401 都算「源活着」，403 算「活着但限制了」。
set -u
MIRRORS=(
  "DaoCloud|docker.m.daocloud.io"
  "1ms.run|docker.1ms.run"
  "1panel|docker.1panel.live"
  "rat.dev|hub.rat.dev"
  "南京大学|docker.nju.edu.cn"
  "腾讯云内网|mirror.ccs.tencentyun.com"
  "官方|registry-1.docker.io"
)
echo "测试各镜像源（每个最多 8 秒）"
echo "------------------------------------------------------------"
printf "  %-12s %-40s %s\n" "来源" "地址" "结果"
BEST=""; BEST_T=99
for m in "${MIRRORS[@]}"; do
  name="${m%%|*}"; host="${m##*|}"
  out=$(curl -s -m 8 -o /dev/null -w "%{http_code} %{time_total}" "https://$host/v2/" 2>/dev/null)
  code="${out%% *}"; sec="${out##* }"
  [ -z "$code" ] && code=000
  case "$code" in
    200|401)  verdict="✓ 可用"; ok=1 ;;
    403)      verdict="~ 活着但限制"; ok=1 ;;
    302)      verdict="~ 重定向"; ok=1 ;;
    000)      verdict="✗ 不通"; ok=0 ;;
    *)        verdict="? HTTP $code"; ok=0 ;;
  esac
  printf "  %-12s %-40s %s (%ss)\n" "$name" "$host" "$verdict" "${sec:-?}"
  if [ "$ok" = "1" ] && [ "$code" != "000" ]; then
    if awk "BEGIN{exit !(${sec:-99} < $BEST_T)}" 2>/dev/null; then
      BEST="$host"; BEST_T="${sec:-99}"
    fi
  fi
done
echo "------------------------------------------------------------"
if [ -n "$BEST" ]; then
  echo "推荐: $BEST  (${BEST_T}s)"
  echo
  echo "两种用法："
  echo "  ① 只改这个项目的构建（不动 Docker 全局配置）"
  echo "     docker compose build --build-arg BASE_IMAGE=$BEST/library/python:3.11-slim"
  echo "     docker compose up -d"
  echo
  echo "  ② 加到 /etc/docker/daemon.json，以后所有镜像都走它"
  echo "     { \"registry-mirrors\": [\"https://$BEST\"] }"
  echo "     改完 systemctl restart docker"
else
  echo "所有源都不通。"
  echo "→ 建议别用 Docker 了，直接 systemd 跑 Python，效果一样："
  echo "   见 部署到1Panel.md 的「方案 C：不用 Docker」"
fi
