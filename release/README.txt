LynkCo Helper · NAS 离线部署包
==============================

说明：这里的“离线包”是指无需 git、无需镜像仓库、无需联网拉取镜像；
运行后的登录和打卡仍然需要访问领克服务器。
如果文件名带 preloaded，说明包内已预置 4 个应用级密钥，只能发给可信朋友，
不要公开上传；它不包含任何人的手机号、refreshToken 或登录态。

一、使用前准备
1. 一台 7x24 在线的 NAS（群晖 / 威联通 / TrueNAS 等），已安装 Docker 或
   Container Manager。
2. 你的领克账号（手机号）和 4 个应用密钥。密钥由发给你压缩包的人提供，
   或使用桌面提取器从 4.3.x APK 中提取。

二、解压
把压缩包解压到 NAS 的一个目录，例如：
  /volume1/docker/lynkco-helper-offline
目录里应有：
  docker-compose.yml
  start.sh / start.command / start.bat
  images/lynkco-helper-amd64.tar
  images/lynkco-helper-arm64.tar
  data/
  README.txt

三、启动
方式 A：SSH 登录 NAS，执行：
  cd /volume1/docker/lynkco-helper-offline
  sh start.sh
  如果提示 permission denied，改用：
  sudo sh start.sh
首次会自动导入镜像（约 1-2 分钟），然后启动容器。

方式 B：群晖 Container Manager
  1. 「映像」→「新增」→「从文件添加」→ 选择 images 下对应架构的 tar；
  2. 「项目」→ 新建 → 选择本目录的 docker-compose.yml；
  3. 启动项目。

方式 C：Windows
  1. 先打开 Docker Desktop，确认使用 Linux containers；
  2. 双击 start.bat，或在 PowerShell 执行：
     .\start.bat
  Windows 不需要 sh，也不需要 sudo。

四、打开网页
浏览器访问：
  http://<NAS的局域网IP>:8000/
如果 8000 端口被占用，编辑 docker-compose.yml，把 "8000:8000" 改成
"18000:8000"，再访问 18000 端口。

五、首次配置
1. 密钥设置：填入 4 个字段
   nativeAppKey / nativeAppSecret / nativeAppCode / loginAppCode
   如果包名带 preloaded，密钥已经填好，跳过本步。
2. 登录：输入手机号 → 完成滑块 → 输入短信验证码。
   注意：这次登录会顶掉你手机 App 的登录，需要时在 App 里重新登录。
3. 打卡：点「立即签到」验证一次；之后每天 08:00（北京时间）自动执行。

六、数据保存
配置保存在 data/env.json，重启容器不会丢。
不要删除 data/ 目录；升级镜像前先备份它。

七、更新
1. 用新的 tar 替换 images/ 下的旧文件；
2. 执行 sh start.sh --force；
   或手动：docker load -i images/lynkco-helper-<arch>.tar
          docker compose up -d

八、安全
- 只建议在局域网使用，不要直接映射到公网。
- 如需在局域网内加保护，在 docker-compose.yml 的 environment 里设置
  LYNKCO_API_TOKEN，并在网页右上角填入同一个令牌。
- 不要把 data/env.json 发给别人。

九、常见问题
- 提示未检测到 docker：先安装 Docker / Container Manager。
- 提示 permission denied：在命令前加 sudo。
- Windows 提示“无法将 sh 项识别为 cmdlet”：改用 .\start.bat，不要用 sh。
- 提示 failed to resolve reference / 403 Forbidden：镜像是从仓库拉取而不是
  本地导入。先手动执行 docker load -i images\lynkco-helper-amd64.tar，
  再执行 docker compose up -d --pull never。
- 提示找不到镜像文件：确认 images/ 目录完整，且选对架构。
- 提示 exec format error：重新执行 sh start.sh --force，让脚本导入当前架构镜像。
- 端口被占用：修改 docker-compose.yml 的端口映射。
- 想改执行时间：设置环境变量 LYNKCO_SCHEDULE_CRON，例如 "30 7 * * *"。
