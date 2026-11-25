# -*- coding: utf-8 -*-
"""pywebview JS bridge for the desktop extractor."""
from pathlib import Path

try:
    from .services import ExtractionError, extract_apk
except ImportError:
    from services import ExtractionError, extract_apk


class ExtractorApi:
    def __init__(self):
        self.window = None

    def pick_apk(self) -> dict:
        if self.window is None:
            return {"ok": False, "error": "桌面窗口尚未就绪"}
        try:
            import webview

            file_dialog = getattr(webview, "FileDialog", None)
            open_dialog = file_dialog.OPEN if file_dialog else webview.OPEN_DIALOG
            result = self.window.create_file_dialog(
                open_dialog,
                allow_multiple=False,
                file_types=("LynkCo APK (*.apk)",),
            )
        except Exception as exc:
            return {"ok": False, "error": f"无法打开文件选择器：{exc}"}
        if not result:
            return {"ok": False, "cancelled": True}
        selected = result[0] if isinstance(result, (list, tuple)) else result
        return {"ok": True, "path": str(Path(selected))}

    def extract(self, apk_path: str) -> dict:
        try:
            result = extract_apk(apk_path)
        except ExtractionError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"提取失败：{exc}"}
        return {"ok": True, **result}
