#!/usr/bin/env python3
"""review/README.md → review/review.html (이미지를 base64로 넣은 오프라인 단일 파일)."""
import base64
import re
from pathlib import Path

import markdown

MANUAL = Path(__file__).resolve().parents[1]
CSS = """
body{max-width:980px;margin:40px auto;padding:0 24px;font:16px/1.7 -apple-system,"Apple SD Gothic Neo",sans-serif;color:#1f2328}
h1{font-size:30px;border-bottom:2px solid #d0d7de;padding-bottom:8px}h2{margin-top:48px;border-bottom:1px solid #d0d7de;padding-bottom:6px}
h3{margin-top:32px}code{font:14px Menlo,monospace;background:#f2f4f7;padding:2px 5px;border-radius:4px}
pre{background:#1e2026;color:#dcdfe4;padding:14px 16px;border-radius:8px;overflow-x:auto}pre code{background:none;color:inherit;padding:0}
img{max-width:100%;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.18);margin:8px 0}
table{border-collapse:collapse;margin:12px 0}th,td{border:1px solid #d0d7de;padding:6px 10px;vertical-align:top}th{background:#f6f8fa}
blockquote{margin:16px 0;padding:8px 16px;border-left:4px solid #8c6bd6;background:#f7f4fd;color:#3d3550}
"""


def github_slug(value: str, separator: str = "-") -> str:
    """GitHub와 같은 앵커: 소문자, 영숫자·한글·공백·하이픈 외 제거, 공백 → 하이픈."""
    value = re.sub(r"[^\w\- ]", "", value.strip().lower())
    return value.replace(" ", separator)


def embed(match: re.Match) -> str:
    src = match.group(2)
    path = MANUAL / src
    if not path.is_file():
        return match.group(0)
    data = base64.b64encode(path.read_bytes()).decode()
    return f'{match.group(1)}data:image/png;base64,{data}"'


def main() -> None:
    md = (MANUAL / "README.md").read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "toc"],
                             extension_configs={"toc": {"slugify": github_slug}})
    body = re.sub(r'(<img[^>]*src=")([^"]+)"', embed, body)
    title = re.search(r"^# (.+)$", md, re.M).group(1)
    html = f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>'
    out = MANUAL / "review.html"
    out.write_text(html, encoding="utf-8")
    print(f"{out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
