"""Собирает статичное демо дашборда (данные зашиты внутрь), чтобы показать пульт без сервера.

    python build_preview.py out.html
"""
import json
import sys

import dashboard

data = dashboard.build_data()
data["messages"] = data["messages"][:700]
body = open(dashboard.TEMPLATE, encoding="utf-8").read()
body = body.replace("/*__DATA__*/", "window.INSPIRE_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";")
out = sys.argv[1] if len(sys.argv) > 1 else "inspire_preview.html"
open(out, "w", encoding="utf-8").write(body)
print(out, round(len(body.encode()) / 1024), "KB")
