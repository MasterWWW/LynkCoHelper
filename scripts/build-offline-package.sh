#!/usr/bin/env bash
set -euo pipefail
export BUILDKIT_PROGRESS=plain

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$ROOT/release/out/lynkco-helper-offline"
IMAGES="$STAGE/images"
PACKAGE_NAME="lynkco-helper-offline"

if ! docker info >/dev/null 2>&1; then
  echo "[错误] Docker 未运行，请先启动 Docker Desktop / dockerd。"
  exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
  echo "[错误] 未找到 docker buildx，请升级 Docker。"
  exit 1
fi

rm -rf "$STAGE"
mkdir -p "$IMAGES" "$STAGE/data"

echo "== 构建 amd64 镜像 =="
docker buildx build \
  --platform linux/amd64 \
  -f "$ROOT/server/Dockerfile" \
  -t lynkco-helper-selfhosted:latest \
  --output "type=docker,dest=$IMAGES/lynkco-helper-amd64.tar" \
  "$ROOT"

echo "== 构建 arm64 镜像 =="
docker buildx build \
  --platform linux/arm64 \
  -f "$ROOT/server/Dockerfile" \
  -t lynkco-helper-selfhosted:latest \
  --output "type=docker,dest=$IMAGES/lynkco-helper-arm64.tar" \
  "$ROOT"

cp "$ROOT/release/docker-compose.yml" "$STAGE/"
cp "$ROOT/release/start.sh" "$STAGE/"
cp "$ROOT/release/start.command" "$STAGE/"
awk '{ sub(/\r$/, ""); printf "%s\r\n", $0 }' "$ROOT/release/start.bat" > "$STAGE/start.bat"
cp "$ROOT/release/README.txt" "$STAGE/"
touch "$STAGE/data/.gitkeep"

if [ -f "$ROOT/release/secrets-only.json" ]; then
  python3 - "$ROOT/release/secrets-only.json" <<'PY'
import json
import sys

path = sys.argv[1]
required = {"nativeAppKey", "nativeAppSecret", "nativeAppCode", "loginAppCode"}
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

if not isinstance(data, dict) or set(data) != {"secrets"}:
    raise SystemExit("[错误] secrets-only.json 只能包含顶层 secrets 字段，不能携带 user/登录态")

secrets = data["secrets"]
if not isinstance(secrets, dict) or set(secrets) != required:
    raise SystemExit("[错误] secrets 必须且只能包含 4 个密钥字段")

if any(not isinstance(value, str) or not value.strip() for value in secrets.values()):
    raise SystemExit("[错误] 4 个密钥字段都必须是非空字符串")
PY
  cp "$ROOT/release/secrets-only.json" "$STAGE/data/env.json"
  PACKAGE_NAME="lynkco-helper-offline-preloaded"
  echo "[提示] 已把 release/secrets-only.json 打进 data/env.json（只应包含 secrets 段）"
  echo "[提示] 本次产物命名为 ${PACKAGE_NAME}.zip，只应发给可信朋友"
fi

chmod +x "$STAGE/start.sh" "$STAGE/start.command"

cd "$ROOT/release/out"
ZIP_NAME="${PACKAGE_NAME}.zip"
rm -f "$ZIP_NAME"
rm -f "${ZIP_NAME}.sha256"
zip -r -q -X "$ZIP_NAME" lynkco-helper-offline
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ZIP_NAME" > "${ZIP_NAME}.sha256"
else
  shasum -a 256 "$ZIP_NAME" > "${ZIP_NAME}.sha256"
fi

echo
echo "完成: $ROOT/release/out/${ZIP_NAME}"
echo "校验: $ROOT/release/out/${ZIP_NAME}.sha256"
du -sh "$ROOT/release/out/${ZIP_NAME}"

if [ "${KEEP_STAGE:-0}" != "1" ]; then
  rm -rf "$STAGE"
fi
