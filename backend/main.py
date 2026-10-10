# -*- coding: utf-8 -*-
"""wx-chat-export 启动入口。

用法:
    python backend/main.py                # 默认 127.0.0.1:8542，自动打开浏览器
    python backend/main.py --host 0.0.0.0 --port 8542 --no-browser
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser


def main() -> None:
    ap = argparse.ArgumentParser(description="微信聊天记录导出（本人账号本地数据）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8542)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器（服务器部署用）")
    ap.add_argument("--window", action="store_true",
                    help="以桌面窗口方式打开（安装 pywebview：pip install pywebview）")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)

    import uvicorn

    if args.window and args.host in ("127.0.0.1", "localhost"):
        def _open_window():
            try:
                import webview
            except ImportError:
                import threading
                import webbrowser
                threading.Timer(1.2, webbrowser.open, args=(f"http://127.0.0.1:{args.port}/",)).start()
                return
            webview.create_window(
                "微信聊天记录", f"http://127.0.0.1:{args.port}/",
                width=1280, height=840, min_size=(980, 640),
            )
            webview.start()

        import threading

        threading.Thread(target=_open_window, daemon=True).start()
    elif not args.no_browser and args.host in ("127.0.0.1", "localhost"):
        threading.Timer(1.2, webbrowser.open, args=(f"http://127.0.0.1:{args.port}/",)).start()

    print(f"* wx-chat-export  http://{args.host}:{args.port}/")
    uvicorn.run("backend.app:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
