# -*- coding: utf-8 -*-
"""端到端请求 /api/media 验证（复用已运行的 8542 服务）。"""
import urllib.error
import urllib.request

ACC = "wxid_your_account_efcf"
BASE = "http://127.0.0.1:8599"
CASES = [
    ("38fcb13ce473eee042b6b219e7edcbbd", "JPEG 266KB 应显示"),
    ("1b455c418160723eebd0d70fc16a43a5", "wxgf 应返回 SVG 占位"),
    ("b7564dff56fbfd50420903d4407d4c97", "wxgf 应返回 SVG 占位"),
    ("eceba4c7c82c7d844010ff98ebeeba98", "普通图片消息，无缓存无密钥 -> 404 提示"),
    ("00000000000000000000000000000000", "不存在的 md5 -> 404"),
]
for md5, note in CASES:
    for variant in ("t", "full"):
        u = (f"{BASE}/api/media?account={ACC}&md5={md5}"
             f"&type=image&variant={variant}")
        try:
            with urllib.request.urlopen(u, timeout=60) as r:
                data = r.read()
                ct = r.headers.get("Content-Type")
                head = data[:4].hex()
                print(f"{md5[:12]} {variant:4} {r.status} {ct:18} {len(data):>8}B "
                      f"head={head}  <- {note}")
        except urllib.error.HTTPError as e:
            body = e.read()[:120].decode("utf-8", "replace")
            print(f"{md5[:12]} {variant:4} {e.code} {'':18} {'':>9}  {body}")
        except Exception as e:
            print(f"{md5[:12]} {variant:4} ERR {e}")
        break