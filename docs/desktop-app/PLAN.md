# LynkCo Helper · 自托管版执行计划

> 给执行 agent 的任务分解。原则：**核心逻辑只做最小新增，业务全部复用
> 现有模块**。每阶段可独立验证。禁止修改签名算法、token 续期、签到/分享
> 接口逻辑。

## 约定

- 工作目录：`LynkCoHelper/`。
- 核心改动仅限：
  1. `lynkco_common.py`：`ENV_FILE` 支持 `LYNKCO_ENV_FILE` 覆盖。
  2. `lynkco_login.py`：抽出 `render_geetest_html()`（返回 HTML 字符串，
     供网页返回）+ 在模板 `onGeetestSuccess` 加 `window.parent.postMessage`。
  3. `tools/appsecret_keyvault.py`：新增暴露 4 槽位的函数，不改默认行为。
- 新代码：`server/`（NAS 主服务）、`desktop/`（提取器）。
- 环境：Python 3.11；服务端依赖 `fastapi`/`uvicorn`/`apscheduler`，
  桌面端 `pywebview`。

## Phase 0 — 核心最小改动

**目标**：让配置路径可指向挂载卷，滑块 HTML 可被网页返回。

- `lynkco_common.py`：
  `ENV_FILE = os.environ.get("LYNKCO_ENV_FILE") or
  os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.json")`。
- `lynkco_login.py`：抽 `render_geetest_html(config, scene) -> str`；让
  `generate_geetest_html()` 调它并写文件（保持 CLI 行为不变）。
- 模板 `onGeetestSuccess` 增加 `window.parent.postMessage({type:
  "geetest-result", payload}, "*")`，包裹 try/catch，不影响复制粘贴路径。

**验证**：`python3 lynkco_login.py <手机号>` 仍能跑通（回归）；
`render_geetest_html` 单独调用返回含 `captchaId` 的 HTML。

**成功标准**：CLI 登录不回归，网页可拿到渲染好的滑块 HTML。

## Phase 1 — NAS 服务骨架 + 持久化目录

**目标**：容器可起服务、可持久化配置。

- 建 `server/main.py`：FastAPI app，`/health`、`/` 静态页占位。
- `server/requirements.txt`、`Dockerfile`、`docker-compose.yml`：
  - `TZ=Asia/Shanghai`
  - `LYNKCO_ENV_FILE=/data/env.json`
  - `volumes: ./data:/data`
  - `restart=unless-stopped`
- 静态页 `server/static/index.html` 四个区块占位（状态/密钥/登录/打卡）。

**验证**：`docker compose up` 后 `curl /health` 返回 ok；容器内
`/data` 可写；`LYNKCO_ENV_FILE` 生效（在容器内 `python3 -c
"import lynkco_common; print(lynkco_common.ENV_FILE)"` 输出 `/data/env.json`）。

**成功标准**：服务可起、卷可挂、配置路径正确。

## Phase 2 — 网页密钥设置

**目标**：网页粘贴 4 个密钥并持久化。

- `server/main.py`：`POST /secrets` 校验 4 字段非空 →
  `save_env_fields(fields, section="secrets")`。
- `GET /status`：返回脱敏状态（`secretsComplete` 等）。
- 前端「密钥设置」区块：4 输入框 + 保存 + 状态刷新。

**验证**：网页保存后，容器 `/data/env.json` 出现 `secrets` 段；重启容器后
仍在；`/status` 的 `secretsComplete=true`。

**成功标准**：密钥写入持久化卷，重启不丢，界面不显示明文（保存后仅显示
已配置/脱敏摘要）。

## Phase 3 — 网页登录（滑块 + 短信）

**目标**：网页完成登录并持久化 refreshToken。

- `server/main.py`：`/login/start`、`/login/geetest`、`/login/validate`、
  `/login/complete`，内存会话 + `threading.Lock`。
- 前端「登录」区块：手机号 → iframe 滑块 → 短信码 → 成功态。
- `/login/complete` 调 `login_with_geetest_and_sms` 写回 `/data/env.json`。

**验证**：真实手机号走一遍，滑完滑块自动进入「验证码已发送」→ 输码 →
`/data/env.json` 出现 `refreshToken/deviceId/token`；重启容器后仍在；
`/status` 的 `hasRefreshToken=true`。

**成功标准**：登录全程在网页完成，登录态持久化，重启不丢。

## Phase 4 — 网页打卡 + 调度 + 状态

**目标**：网页手动打卡、每日定时、展示打卡情况。

- `server/main.py`：`POST /run`（调 `load_token()` +
  `run_daily_tasks(token)`，脱敏结果存最近报告）、`GET /report`；
  APScheduler 定时任务与 `/run` 共用运行中锁。
- 前端「打卡」区块：「立即签到」按钮 + 加载态 + 结果展示（积分前后、
  签到状态、成长值、任务、分享标题、失败原因）。
- 「状态」区块：最近打卡时间/摘要。

**验证**：配好密钥+登录态后，点「立即签到」成功并展示结果；把
`LYNKCO_SCHEDULE_CRON` 改成 1 分钟验证调度在 `Asia/Shanghai` 执行；
连续两次 `/run` 第二次返回 409。

**成功标准**：手动与定时打卡都可用，结果正确、脱敏，防重入生效。

## Phase 5 — 桌面提取器（4 字段映射）

**目标**：桌面选择 APK → 输出 4 个密钥。

- 调查并扩展 `tools/appsecret_keyvault.py`：新增 `extract_all(apk)` 返回
  4 槽位 `(code, key, secret)`，建立到 4 字段的映射（真机/交叉验证），
  不改默认 `extract()`。
- `desktop/`：`main.py` + `api.py` + `services.py`（仅调提取）+ 单页
  「选 APK → 展示/复制 4 字段」。
- 失败分支：无 KeyVault → 「仅支持 4.3.x」；损坏/未知布局 → 具体原因。

**验证**：用 4.3.1 APK 提取，4 字段齐；`loginAppCode` 能支撑网页登录、
`nativeAppCode` 能支撑续期（真机各验一次）。

**成功标准**：桌面输出 4 字段可填入网页并跑通登录/打卡。若映射无法确定，
按 DESIGN R1 降级为「输出 2 字段 + 网页 4 输入框补齐」。

## Phase 6 — 部署文档 + 通知口子说明

**目标**：可照做部署，通知口子留好。

- `server/README.md`：Synology（Container Manager）/ QNAP / TrueNAS 部署
  步骤、端口、卷、`LYNKCO_SCHEDULE_CRON`、`LYNKCO_API_TOKEN` 说明。
- 更新 `LynkCoHelper/readme.md`：新增「自托管版」小节，说明桌面提取密钥 →
  网页配置密钥+登录 → 打卡；通知标注「后续版本」。
- 确认 `lynkco_notify` 调用链保留、网页不实现通知 UI（口子已留）。

**验证**：按 README 从零在 NAS 部署，完成密钥配置 + 登录 + 手动打卡一次。

**成功标准**：文档与实际行为一致；通知口子清晰可续做。

## 交付清单

- [ ] `server/` 全部新文件（含 Dockerfile / compose / README / static）
- [ ] `desktop/` 全部新文件
- [ ] 核心最小改动（`lynkco_common.py` / `lynkco_login.py` /
  `tools/appsecret_keyvault.py`）
- [ ] `LynkCoHelper/readme.md` 自托管版说明
- [ ] 不提交 `env.json` / 任何密钥 / 挂载的 `data/`

## Phase 7 — 离线发布包

**目标**：朋友拿到压缩包后不需要 git、Python 或镜像仓库，解压即可启动。

- `release/`：发布用 compose、跨平台启动脚本、ASCII 文件名的中文说明。
- `scripts/build-offline-package.sh`：用 buildx 分别导出 amd64/arm64 镜像 tar，
  组装目录并生成 zip + SHA-256。
- `release/secrets-only.json` 可选：仅允许预置 4 个应用密钥；构建时校验，
  拒绝携带 `user`/refreshToken 的配置。预置包单独命名为
  `lynkco-helper-offline-preloaded.zip`，避免与可公开的干净包混淆。
- 镜像和发布包不得包含 `env.json`、挂载数据、HAR 或真实凭据。

**验证**：

- 在本机实际执行完整构建，确认两个镜像 tar 的平台分别为 amd64/arm64。
- 按最终 zip 解压后的原始目录执行 `start.sh --force`，确认可导入镜像、启动
  容器并通过 `/health`。
- 用空 `data/` 启动，确认 `secretsComplete=false`，证明没有把本机配置打进包。
- 检查 zip 中不含 `env.json`，且所有路径均为 ASCII，避免 Windows 解压乱码。
