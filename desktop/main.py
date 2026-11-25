# -*- coding: utf-8 -*-
"""Launch the desktop APK key extractor."""
import sys
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent
if str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))

from api import ExtractorApi  # noqa: E402


def main() -> None:
    try:
        import webview
    except ImportError:
        sys.exit("缺少 pywebview，请先执行: pip install -r desktop/requirements.txt")

    api = ExtractorApi()
    window = webview.create_window(
        title="LynkCo 密钥提取器",
        url=(DESKTOP_DIR / "static" / "index.html").as_uri(),
        js_api=api,
        width=960,
        height=780,
        min_size=(720, 600),
        background_color="#080b0e",
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
