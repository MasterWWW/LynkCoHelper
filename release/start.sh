#!/bin/sh
set -eu
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "[错误] 未检测到 docker，请先在 NAS 上安装 Docker / Container Manager。"
  exit 1
fi

case "$(uname -m)" in
  x86_64|amd64)
    TAR="images/lynkco-helper-amd64.tar"
    WANT_ARCH="amd64"
    ;;
  aarch64|arm64)
    TAR="images/lynkco-helper-arm64.tar"
    WANT_ARCH="arm64"
    ;;
  *)
    echo "[错误] 不支持的 CPU 架构: $(uname -m)"
    exit 1
    ;;
esac

FORCE=0
if [ "${1:-}" = "--force" ]; then
  FORCE=1
fi

IMAGE_ARCH=$(docker image inspect --format '{{.Architecture}}' lynkco-helper-selfhosted:latest 2>/dev/null || true)
if [ -n "$IMAGE_ARCH" ] && [ "$IMAGE_ARCH" != "$WANT_ARCH" ]; then
  echo "[提示] 本地镜像架构为 ${IMAGE_ARCH}，与当前 NAS 的 ${WANT_ARCH} 不匹配，将重新导入。"
  FORCE=1
fi

if [ "$FORCE" = "1" ] || ! docker image inspect lynkco-helper-selfhosted:latest >/dev/null 2>&1; then
  if [ ! -f "$TAR" ]; then
    echo "[错误] 找不到镜像文件 ${TAR}，请确认压缩包完整且架构匹配。"
    exit 1
  fi
  echo "正在导入镜像（首次约 1-2 分钟）..."
  docker load -i "$TAR"
fi

if docker compose version >/dev/null 2>&1; then
  docker compose up -d
else
  docker-compose up -d
fi

IP=""
if command -v ip >/dev/null 2>&1; then
  IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || true)
elif command -v ipconfig >/dev/null 2>&1; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || true)
fi

echo
echo "已启动。浏览器打开: http://${IP:-<NAS-IP>}:8000/"
echo "查看日志: docker logs -f lynkco-helper"
