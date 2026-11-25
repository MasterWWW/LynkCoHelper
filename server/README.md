# LynkCo Helper · NAS 自托管版

FastAPI 主服务 + 单页管理界面。密钥、登录态和最近一次打卡报告都写入容器挂载卷，
容器替换或重启不会丢失配置。

## 功能

- 网页保存 4 个密钥字段，保存后不回显明文。
- 网页完成极验滑块 + 短信验证码登录，持久化 `refreshToken/deviceId/token`。
- 手动签到 + 分享，展示积分、签到状态、成长值、任务进度和分享标题。
- APScheduler 每天北京时间自动执行；手动与定时任务共用运行锁。
- 可选 `X-API-Token` 保护写入接口。
- 通知调用链保留：配置 `env.json` 的 `notify` 段后，任务结束会调用现有
  `lynkco_notify`；当前版本不提供通知设置 UI。

## 快速部署

### Docker Compose

在仓库的 `server/` 目录执行：

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

打开 `http://<NAS-IP>:8000/`，按「密钥设置 → 手机号登录 → 立即签到」操作。

默认挂载：

| 宿主机 | 容器 | 用途 |
| --- | --- | --- |
| `server/data/` | `/data` | `env.json` 与 `last_report.json` |

首次启动会自动创建 `server/data/`；保存密钥或完成登录后生成
`server/data/env.json`。该目录已被 `.gitignore` 忽略，不要提交或上传到
公开位置。

### 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
LYNKCO_ENV_FILE="$PWD/server/data/env.json" \
  PYTHONPATH="$PWD/LynkCoHelper:$PWD" \
  uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Python 3.11 为推荐版本。

## 配置

容器只通过以下环境变量控制服务行为。密钥、token 等配置全部在 `/data/env.json`，
不要改用 `LYNKCO_APP_SECRETS`、`LYNKCO_TOKEN` 等环境变量。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `LYNKCO_ENV_FILE` | `/data/env.json` | 持久化配置文件路径 |
| `LYNKCO_SCHEDULE_CRON` | `0 8 * * *` | 5 段 cron，固定按 `Asia/Shanghai` 解释 |
| `LYNKCO_API_TOKEN` | 空 | 可选访问令牌；配置后写入接口要求 `X-API-Token` |
| `LYNKCO_LOG_LEVEL` | `INFO` | 日志级别 |

在网页右上角填写与服务端相同的访问令牌，令牌只保存在当前浏览器的
`localStorage`。服务端设置 `LYNKCO_API_TOKEN` 后，以下接口受保护：

- `POST /secrets`
- `POST /login/start`
- `GET /login/geetest`
- `POST /login/validate`
- `POST /login/complete`
- `POST /run`

## 数据与重启

`/data/env.json` 保存：

- `secrets`：4 个应用密钥字段。
- `user`：`refreshToken`、`deviceId`、缓存的 `token` 与过期时间。
- `notify`：通知配置口子，当前无 UI。

`/data/last_report.json` 保存最近一次脱敏打卡报告，用于重启后继续展示。
不包含 token、手机号或密钥。

验证重启持久化：

```bash
docker compose restart
curl -s http://127.0.0.1:8000/status
```

`secretsComplete` 和 `hasRefreshToken` 应保持为 `true`。

## NAS 平台

### Synology Container Manager

1. 将仓库放到 NAS 共享目录，进入 `server/`。
2. 在「项目」中新建 Compose 项目，路径选择 `server/docker-compose.yml`。
3. 如镜像拉取/构建权限受限，先在可运行 Docker 的机器执行
   `docker build -f server/Dockerfile -t lynkco-helper-selfhosted:latest .`，
   再导入 NAS 或改用 NAS 可访问的私有镜像仓库。
4. 启动后访问 `http://<NAS-IP>:8000/`。

### QNAP / TrueNAS / 通用 Linux

在 `server/` 目录执行 `docker compose up -d --build`。端口冲突时修改
`docker-compose.yml` 左侧端口，例如 `"18000:8000"`。

## 桌面端配合

桌面提取器只负责离线解析 4.3.x APK：

```bash
pip install -r desktop/requirements.txt
python3 desktop/main.py
```

把输出的 `nativeAppKey/nativeAppSecret/nativeAppCode/loginAppCode` 粘贴到网页
「密钥设置」。若提取器遇到不含 KeyVault 的 APK，会提示仅支持 4.3.x，不会尝试
套用错误偏移。

## 调度与防重入

- 调度器显式使用 `Asia/Shanghai`，容器同时设置 `TZ=Asia/Shanghai`。
- `/run` 与定时任务共用同一把非阻塞锁；运行中再次触发 `/run` 返回 HTTP 409。
- 任务异常会写入最近报告，服务继续存活。
- 支持 APScheduler 5 段 cron，前后不能有无效字段，例如 `30 8 * * 1-5`。

只验证调度而不真实打卡，可使用较短的测试时间并观察 `/status` 的 `nextRun`；
真实打卡需要先完成登录。

## 安全建议

- NAS 仅在可信局域网开放，或通过反向代理 + HTTPS 访问。
- 建议设置 `LYNKCO_API_TOKEN`，避免局域网内其他人修改密钥或触发短信。
- 不要把 `server/data/`、`env.json`、HAR 文件或 APK 提交到仓库。
- 更新镜像前备份 `server/data/`。

## 验证清单

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/status
docker exec lynkco-helper python3 -c \
  "import lynkco_common; print(lynkco_common.ENV_FILE)"
```

期望最后一条输出 `/data/env.json`。容器内 `/data` 应可写，重启后
`secretsComplete` 与 `hasRefreshToken` 不变。
