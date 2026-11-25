# -*- coding: utf-8 -*-
"""Offline 4.3.x APK key extraction used by the desktop UI."""
import sys
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DESKTOP_DIR.parent
TOOLS_DIR = PROJECT_ROOT / "LynkCoHelper" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from appsecret_keyvault import UnsupportedKeyVault, extract_all  # noqa: E402


SECRET_FIELDS = (
    "nativeAppKey",
    "nativeAppSecret",
    "nativeAppCode",
    "loginAppCode",
)


class ExtractionError(ValueError):
    """A user-readable extraction failure."""


def extract_apk(apk_path: str) -> dict:
    path = Path(apk_path).expanduser()
    if not path.exists():
        raise ExtractionError("找不到所选 APK 文件")
    if not path.is_file():
        raise ExtractionError("所选路径不是文件")
    if path.suffix.lower() != ".apk":
        raise ExtractionError("请选择 .apk 文件")

    try:
        fields = extract_all(str(path))
    except UnsupportedKeyVault as exc:
        raise ExtractionError(str(exc)) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise ExtractionError(f"APK 解析失败：{exc}") from exc

    if any(not isinstance(fields.get(name), str) or not fields[name] for name in SECRET_FIELDS):
        raise ExtractionError("KeyVault 解析结果不完整")
    return {
        "fields": {name: fields[name] for name in SECRET_FIELDS},
        "file": {
            "name": path.name,
            "size": path.stat().st_size,
        },
    }
