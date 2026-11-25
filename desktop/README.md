# LynkCo 密钥提取器

桌面端只做一件事：选择领克 4.3.x APK，离线提取 4 个密钥字段。

```bash
python3 -m venv .venv-desktop
source .venv-desktop/bin/activate
pip install -r desktop/requirements.txt
python3 desktop/main.py
```

输出：

- `nativeAppKey`
- `nativeAppSecret`
- `nativeAppCode`
- `loginAppCode`

## 映射依据

`tools/appsecret_keyvault.py` 在 4.3.1 的
`lib/arm64-v8a/libkeyvault.so`（sha256 前缀 `283359da`）中读取 4 个固定槽位：

- `SWGeelyCode`：生产原生签名槽位，取第一条的 key/secret 作为
  `nativeAppKey`/`nativeAppSecret`；`nativeAppCode` 为该 code。
- `user_module`：滑块登录使用的 `loginAppCode`。

不支持的 KeyVault 布局、损坏 APK 和不含 KeyVault 的 4.2.9 会直接给出错误，
不会猜测偏移。桌面端不包含登录、签到或定时逻辑。

## 说明

- 文件选择器由 pywebview 原生对话框提供。
- 如果文件选择器不可用，可将 APK 完整路径粘贴到页面输入框再提取。
- 提取完全在本机完成，不发起网络请求。
