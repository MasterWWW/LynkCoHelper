# LynkCo Helper · 自托管版框架设计

> 状态：待评审执行。本文档描述「NAS 自托管 + 桌面提取器」的架构，执行细节见
> `PLAN.md`，审查标准见 `REVIEW.md`。

## 1. 目标与非目标

### 目标

把一个面向命令行的领克 App 自动签到项目，重构成两个形态，核心逻辑复用：

1. **桌面提取器**：只做一件事——选择/拖入 4.3.x 的领克 APK，离线静态提取
   密钥四个字段（`nativeAppKey/nativeAppSecret/nativeAppCode/loginAppCode`），
   展示并复制给用户。
2. **NAS 容器（主入口）**：Docker 部署一个常驻服务 + 网页，负责
   - 配置：网页填入选好的密钥并持久化。
   - 登录：网页内完成极验滑块 + 短信验证码，拿到并持久化 `refreshToken`。
   - 打卡：每日定时自动签到+分享；网页可手动打卡；网页展示打卡情况。
   - 通知：只留口子（配置结构 + 调用链），本阶段不做通知 UI。

### 非目标

- 不重写签名算法、token 续期、签到/分享核心逻辑。
- 不解决极验滑块全自动化（网页内人工滑一次）。
- 桌面端不做登录、打卡、定时（全归 NAS）。
- 不支持旧版 APK（无 KeyVault 的 4.2.9）模拟器/JDWP 提取。

## 2. 总体拓扑与数据流

| 组件 | 部署方式 | 职责 |
| --- | --- | --- |
| 桌面提取器 | 本地桌面 App | 上传 APK → 输出 4 个密钥 |
| NAS 容器 | Docker（Synology / QNAP / TrueNAS） | 网页配置密钥 + 登录 + 每日/手动打卡 + 展示 |
| GitHub Actions | 托管 runner | 可选兜底（已有，不动） |

数据流：桌面提取器输出 4 个密钥 → 用户在网页「密钥设置」粘贴并保存 →
容器写入持久化卷；用户在网页「登录」完成滑块+短信 → 容器写入
`refreshToken/deviceId/token` 到同一持久化卷。之后容器即可定时/手动打卡。

## 3. 技术选型

### NAS 服务：FastAPI + APScheduler + Docker

- **必要性**：NAS 7×24 在线、私密；网页承载「配置密钥 / 登录 / 打卡 / 状态」，
  一个容器完整可用。
- **成本**：新增 `fastapi` / `uvicorn` / `apscheduler` 三个服务端依赖。
- **资源要求（低）**：`python:3.11-slim` 约 150–200MB 磁盘，空闲内存几十 MB、
  任务峰值约 100–150MB，入门级 arm64/armv7 NAS 可跑。

### 桌面提取器：Python + pywebview（轻量单页）

- 单功能：选 APK → 显示/复制 4 个密钥。pywebview 复用系统 WebView，实现简单；
  若想零依赖可退化为 `tkinter` 对话框，首版保留 pywebview。

## 4. 目录结构

```text
LynkCoHelper/
  lynkco_common.py          # 现有：最小新增 LYNKCO_ENV_FILE 支持
  lynkco_login.py           # 现有：最小新增 render_geetest_html + postMessage
  lynkco_sign.py            # 现有
  lynkco_share.py           # 现有
  lynkco_notify.py          # 现有：通知调用链（本阶段只留口子）
  lynkco_daily_tasks.py     # 现有
  tools/
    appsecret_keyvault.py   # 现有：需扩展暴露 4 槽位映射
    appsecret_core.py       # 现有
  server/                   # 新增：NAS 自托管服务（主入口）
    __init__.py
    main.py                 # FastAPI + APScheduler + 会话/鉴权
    requirements.txt        # fastapi / uvicorn / apscheduler
    Dockerfile
    docker-compose.yml
    README.md               # NAS 部署说明
    static/
      index.html            # 管理页：状态 / 密钥设置 / 登录 / 打卡
      app.css
      app.js
  desktop/                  # 新增：桌面提取器（单功能）
    __init__.py
    main.py
    api.py
    services.py             # 仅封装 appsecret_keyvault 提取
    static/index.html       # 选 APK → 提取 → 展示/复制 4 字段
  env.json.example
docs/desktop-app/
  DESIGN.md
  PLAN.md
  REVIEW.md
```

## 5. 持久化设计（关键）

**目标：密钥 + refreshToken 都要在容器重启后保留。**

- 容器挂载卷：宿主机目录 → 容器内 `/data`。
- 核心最小改动：`lynkco_common.py` 的 `ENV_FILE` 支持
  `LYNKCO_ENV_FILE` 环境变量覆盖，默认仍为模块目录下的 `env.json`。
- 容器设置 `LYNKCO_ENV_FILE=/data/env.json`。
- 网页「密钥设置」写 `env.json` 的 `secrets` 段（复用 `save_env_fields(fields,
  section="secrets")`）。
- 网页「登录」写 `env.json` 的 `user` 段（复用
  `login_with_geetest_and_sms`，其内部已 `save_env_fields`）。

因此容器**不需要** `LYNKCO_APP_SECRETS` / `LYNKCO_TOKEN` /
`LYNKCO_REFRESH_TOKEN` / `LYNKCO_DEVICE_ID` 环境变量；配置全部落在
`/data/env.json`，`load_token()` 与签名逻辑从该文件读取。

## 6. 网页端功能

单页四个区块：

1. **状态总览**：密钥是否已配齐、`refreshToken` 是否有效、最近打卡时间与
   结果摘要（脱敏）。
2. **密钥设置**：4 个输入框（nativeAppKey/nativeAppSecret/nativeAppCode/
   loginAppCode）+ 保存；成功后 `secretsComplete` 变 true。
3. **登录**：手机号 → 内嵌滑块 iframe → 短信验证码 → 完成登录；成功后
   `refreshToken` 状态变 true。
4. **打卡**：手动「立即签到」按钮 + 最近一次结果（积分前后、签到状态、
   成长值、任务、分享标题）+ 每日调度状态。

### 通知口子（本阶段不做 UI）

- `env.json` 已有 `notify` 段，`run_and_notify()` 已调用
  `send_notifications()`；网页暂不提供通知配置表单。
- 后续加「通知设置」区块即可，核心与调度无需改动。

## 7. 接口设计

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/` | 返回管理页 |
| GET | `/health` | 存活检查 |
| GET | `/status` | 脱敏配置状态 + 最近运行摘要 |
| POST | `/secrets` | body 为 4 字段，保存到 `secrets` 段 |
| POST | `/login/start` | body `{phone}`：生成滑块会话，返回 `sid` |
| GET | `/login/geetest?sid=` | 返回渲染好的滑块 HTML（iframe 加载） |
| POST | `/login/validate` | 校验滑块结果并发短信 |
| POST | `/login/complete` | body `{code}`：短信码登录并持久化 |
| POST | `/run` | 立即执行每日任务 |
| GET | `/report` | 最近一次运行结果（脱敏） |

鉴权：可选 `LYNKCO_API_TOKEN`，客户端带 `X-API-Token`；未配置时仅依赖
NAS 局域网隔离。登录相关写接口（`/login/*`、`/secrets`）建议鉴权，防短信
轰炸与越权改配置。

## 8. 网页登录流程（滑块进容器）

1. `POST /login/start`：`get_security_config(device_id)` →
   `render_geetest_html(...)` 生成 HTML；内存会话保存 deviceId/phone/步骤。
2. 前端 `<iframe src="/login/geetest?sid=...">` 加载滑块。
3. 用户滑完，模板 `onGeetestSuccess` 用 `window.parent.postMessage(...)`
   回传结果。
4. `POST /login/validate`：`validate_geetest` → `send_login_sms`。
5. `POST /login/complete`：`login_with_geetest_and_sms` 写回 `/data/env.json`。

会话：单用户 NAS，内存单会话 + `threading.Lock` 串行化。

## 9. 调度与防重入

- APScheduler `CronTrigger(timezone="Asia/Shanghai")`，读
  `LYNKCO_SCHEDULE_CRON`（默认 `0 8 * * *`）。
- 定时与手动 `/run` 共用运行中锁，运行中再次触发返回 409。
- 任务异常不影响服务存活，结果脱敏后存最近报告。

## 10. 安全边界

- 网页/接口不回显明文，日志走 `mask_sensitive` / `mask_secret`。
- `env.json` 只在挂载卷落盘，不进镜像、不入库。
- 登录相关写接口鉴权，防短信轰炸。

## 11. 风险与决策记录

- **R1（最高）**：现有 `appsecret_keyvault.extract()` 只返回
  `nativeAppKey`+`nativeAppSecret`；但网页登录需要 `loginAppCode`，续期
  方案一需要 `nativeAppCode`。桌面提取器需扩展暴露 4 槽位并真机验证映射；
  无法可靠确定时降级为「输出 2 字段 + 网页手动补 4 字段」。
- **R2**：极验滑块无法全自动，网页内人工滑一次，属预期。
- **R3**：APScheduler 必须显式 `Asia/Shanghai` 且容器 `TZ=Asia/Shanghai`。
- **R4**：`save_env_fields` 读改写无锁；服务层用锁串行化写操作，不侵入核心。
- **R5**：分享任务每日有上限，重复触发不重复加分；`/run` 防重入锁兜底。
