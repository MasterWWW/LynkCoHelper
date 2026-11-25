@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 docker，请先安装 Docker Desktop。
  pause
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo [错误] Docker Desktop 未启动，或 Docker 引擎尚未就绪。
  echo 请打开 Docker Desktop，等待引擎运行后重试。
  pause
  exit /b 1
)

set "DOCKER_OS="
for /f "usebackq delims=" %%i in (`docker info --format "{{.OSType}}"`) do set "DOCKER_OS=%%i"
if /I not "%DOCKER_OS%"=="linux" (
  echo [错误] Docker Desktop 当前不是 Linux containers 模式。
  echo 请右键系统托盘中的 Docker 图标，选择 Switch to Linux containers 后重试。
  pause
  exit /b 1
)

if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
  set "TAR=images\lynkco-helper-arm64.tar"
  set "WANT_ARCH=arm64"
) else (
  set "TAR=images\lynkco-helper-amd64.tar"
  set "WANT_ARCH=amd64"
)

set "IMAGE_ARCH="
for /f "usebackq delims=" %%i in (`docker image inspect --format "{{.Architecture}}" lynkco-helper-selfhosted:latest 2^>nul`) do set "IMAGE_ARCH=%%i"

set "NEED_LOAD=0"
if not defined IMAGE_ARCH (
  set "NEED_LOAD=1"
) else (
  if /I not "%IMAGE_ARCH%"=="%WANT_ARCH%" (
    echo [提示] 本地镜像架构为 %IMAGE_ARCH%，与当前 Windows 的 %WANT_ARCH% 不匹配，将重新导入。
    set "NEED_LOAD=1"
  )
)

if "%NEED_LOAD%"=="1" (
  if not exist "%TAR%" (
    echo [错误] 找不到镜像文件 %TAR%，请确认压缩包完整。
    pause
    exit /b 1
  )
  echo 正在导入镜像（首次约 1-2 分钟）...
  docker load -i "%TAR%"
  if errorlevel 1 (
    echo [错误] 镜像导入失败。请确认 Docker Desktop 使用 Linux containers。
    pause
    exit /b 1
  )
)

docker image inspect lynkco-helper-selfhosted:latest >nul 2>nul
if errorlevel 1 (
  echo [错误] 镜像导入后仍未找到 lynkco-helper-selfhosted:latest。
  pause
  exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 docker compose，请升级 Docker Desktop。
  pause
  exit /b 1
)

docker compose up -d --pull never
if errorlevel 1 (
  echo [错误] 容器启动失败，请查看上方错误信息。
  pause
  exit /b 1
)

start "" "http://127.0.0.1:8000/"
echo 已启动: http://127.0.0.1:8000/
pause
