# LynkCo Helper · 自托管版审查计划

> 执行 agent 完成后，由 `/root` 按本清单审查。任何一项「不通过」即退回，
> 附带具体文件/行号与修复建议。

## 0. 原则

- 最小改动：核心业务（签名/续期/签到/分享）只允许最小新增，不允许重构。
- 不泄密：diff 中不得出现真实 token/refreshToken/appSecret/AppCode。
- 持久化正确：密钥与 refreshToken 都要落挂载卷，重启不丢。

## 1. 范围与 diff

- [ ] `git status --short` 无 `env.json`、`geetest_helper.html`、`data/`、
  `*.har`、`res.json` 等敏感/临时文件。
- [ ] `git diff` 确认核心改动仅三处：
  - `lynkco_common.py` 的 `ENV_FILE` 覆盖。
  - `lynkco_login.py` 的 `render_geetest_html` + postMessage。
  - `tools/appsecret_keyvault.py` 的 `extract_all`（不改 `extract()` 默认）。

## 2. 持久化

- [ ] `LYNKCO_ENV_FILE` 生效，容器内指向 `/data/env.json`。
- [ ] 网页「密钥设置」写 `secrets` 段，「登录」写 `user` 段。
- [ ] 重启容器后密钥与 refreshToken 仍在（端到端验证）。
- [ ] 容器未设置 `LYNKCO_APP_SECRETS` / `LYNKCO_TOKEN` /
  `LYNKCO_REFRESH_TOKEN` / `LYNKCO_DEVICE_ID`，配置全走挂载文件。

## 3. 网页功能

- [ ] `/status` 脱敏返回密钥是否配齐、refreshToken 是否有效、最近打卡摘要。
- [ ] `/secrets` 校验 4 字段，保存后不把明文回显到前端。
- [ ] 登录链路：`/login/start → /login/geetest → /login/validate →
  /login/complete` 状态机完整，含异常清理与锁。
- [ ] 手动打卡按钮 + 结果展示正确（积分前后、签到状态、成长值、任务、
  分享标题），失败有可读原因。
- [ ] 通知口子：`lynkco_notify` 调用链保留，网页未实现通知 UI（符合预期）。

## 4. 调度与防重入

- [ ] APScheduler 显式 `Asia/Shanghai`，容器 `TZ=Asia/Shanghai`。
- [ ] `/run` 与定时共用运行中锁，重复触发返回 409 或幂等。
- [ ] 任务异常不影响服务存活，结果脱敏落最近报告。

## 5. 桌面提取器

- [ ] 4 槽位到 4 字段映射有证据（注释或验证记录），非猜测。
- [ ] 损坏/无 KeyVault/未知布局 APK 错误文案准确、不崩溃。
- [ ] 仅输出密钥，不含登录/打卡/定时逻辑。

## 6. 安全

- [ ] 网页/接口/日志不回显明文，走 `mask_sensitive` / `mask_secret`。
- [ ] `/login/*`、`/secrets` 受可选 `LYNKCO_API_TOKEN` 鉴权保护。
- [ ] `env.json` 只在挂载卷落盘，不进镜像、不入库。

## 7. 端到端验证（需真实凭据）

- [ ] 桌面用 4.3.1 APK 提取出 4 字段。
- [ ] 网页填入 4 字段并保存，`secretsComplete=true`。
- [ ] 网页滑块+短信登录，`refreshToken` 持久化。
- [ ] 网页手动打卡成功，结果正确。
- [ ] 重启容器后，密钥+登录态仍在，无需重新配置。
- [ ] 定时任务在 `Asia/Shanghai` 正确触发。

## 8. 放行条件

- 第 1、2、6 项全部通过；第 3–5 项无 P0。
- 无敏感信息入库；核心模块 diff 符合最小改动原则。
- README 与实际行为一致，通知口子明确标注「后续版本」。
