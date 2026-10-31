#!/usr/bin/env python3
"""Run a shell command, save its real output, and render it as a terminal-style PNG.

Usage:
  capture.py <name> [--title TEXT] [--max-lines N] [--tail] -- <command ...>

Writes manual/logs/<name>.txt (full output), manual/logs/<name>.meta.json (render options)
and manual/images/<name>.png. The command runs from the project root through zsh, exactly as typed.

  capture.py --rerender <name>   # redraw the PNG from the saved log without running anything
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "review"
MONO = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 26)
MONO_BOLD = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 26, index=1)
WIDE = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", 26)
CELL_W = int(MONO.getlength("M"))
LINE_H = 36
PAD = 28
BAR_H = 48
MAX_COLS = 110

BG = (30, 32, 38)
BAR = (44, 47, 55)
FG = (220, 223, 228)
DIM = (140, 146, 158)
PROMPT = (126, 200, 140)
RED = (240, 110, 110)
GREEN = (126, 200, 140)
YELLOW = (230, 196, 110)


def is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) > 0x2000


def advance(ch: str) -> float:
    """한글 등은 고정 2칸이 아니라 글꼴의 실제 폭으로 그린다(글자 사이 빈틈 방지)."""
    return WIDE.getlength(ch) if is_wide(ch) else CELL_W


def wrap(line: str) -> list[str]:
    out, cur, width, limit = [], "", 0.0, CELL_W * MAX_COLS
    for ch in line.expandtabs(4):
        w = advance(ch)
        if width + w > limit:
            out.append(cur)
            cur, width = "", 0.0
        cur += ch
        width += w
    out.append(cur)
    return out


def color_for(line: str) -> tuple[int, int, int]:
    low = line.lower()
    if line.startswith("$ "):
        return PROMPT
    if any(k in low for k in ("fail", "error", "traceback", "refused", "denied")) and "0 fail" not in low:
        return RED
    if any(k in low for k in (" ok", "passed", "pass ", "success", "completed")):
        return GREEN
    if low.startswith(("warning", "note", "...")):
        return YELLOW
    return FG


def render(title: str, lines: list[str], dest: Path) -> None:
    rows: list[tuple[str, tuple[int, int, int], bool]] = []
    for line in lines:
        color = color_for(line)
        bold = line.startswith("$ ")
        for part in wrap(line):
            rows.append((part, color, bold))
    width = int(PAD * 2 + max([sum(advance(c) for c in r[0]) for r in rows] + [CELL_W * 60]))
    height = BAR_H + PAD * 2 + LINE_H * max(len(rows), 1)
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, BAR_H], fill=BAR)
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        x = 24 + i * 28
        draw.ellipse([x, 16, x + 16, 32], fill=c)
    draw.text((120, 10), title, font=WIDE, fill=DIM)
    y = BAR_H + PAD
    for text, color, bold in rows:
        x = PAD
        for ch in text:
            font = WIDE if is_wide(ch) else (MONO_BOLD if bold else MONO)
            draw.text((x, y), ch, font=font, fill=color)
            x += advance(ch)
        y += LINE_H
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, optimize=True)


def draw_capture(name: str, title: str, shown: str, output: str, code: int, max_lines: int, tail: bool) -> None:
    body = output.splitlines()
    if len(body) > max_lines:
        omitted = len(body) - max_lines
        note = f"... ({omitted}줄 생략, 전체는 logs/{name}.txt)"
        body = [note] + body[-max_lines:] if tail else body[:max_lines] + [note]
    render(title, [f"$ {shown}", *body, f"[exit {code}]"], MANUAL / "images" / f"{name}.png")


def rerender(name: str) -> int:
    meta = json.loads((MANUAL / "logs" / f"{name}.meta.json").read_text(encoding="utf-8"))
    lines = (MANUAL / "logs" / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
    shown, code = lines[0][2:], int(lines[-1][len("[exit "):-1])
    draw_capture(name, meta["title"], shown, "\n".join(lines[1:-1]), code, meta["max_lines"], meta["tail"])
    print(f"redrawn images/{name}.png")
    return 0


def main() -> int:
    if sys.argv[1:2] == ["--rerender"]:
        return rerender(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--title", default="Terminal — harness101-local")
    ap.add_argument("--max-lines", type=int, default=40)
    ap.add_argument("--tail", action="store_true", help="show the last lines instead of the first")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--display", help="command text to show instead of the real one")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    shell_cmd = " ".join(cmd)
    proc = subprocess.run(
        ["zsh", "-c", shell_cmd], cwd=ROOT, env={**os.environ, "PATH": f"/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:{os.environ['PATH']}"}, capture_output=True, text=True, timeout=args.timeout
    )
    output = (proc.stdout + proc.stderr).rstrip("\n")
    shown = args.display or shell_cmd
    log = MANUAL / "logs" / f"{args.name}.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"$ {shown}\n{output}\n[exit {proc.returncode}]\n", encoding="utf-8")
    meta = {"title": args.title, "max_lines": args.max_lines, "tail": args.tail}
    (MANUAL / "logs" / f"{args.name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    draw_capture(args.name, args.title, shown, output, proc.returncode, args.max_lines, args.tail)
    print(output)
    print(f"[exit {proc.returncode}] -> images/{args.name}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
