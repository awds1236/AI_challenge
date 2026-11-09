"""프로그램 아이콘(seomu/assets/app.ico) 만들기 — 화면 왼쪽 위 로고와 같은 모양 (파란 둥근 사각형 + 문서).

    python tools/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "seomu" / "assets" / "app.ico"


def draw(size: int = 256) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 배경: 위는 밝은 파랑, 아래는 짙은 파랑 (세로 그라데이션)
    top, bottom = (64, 156, 255), (10, 92, 230)
    grad = Image.new("RGBA", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / (size - 1)
        gd.line([(0, y), (size, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(56 * s), fill=255)
    img.paste(grad, (0, 0), mask)
    # 문서 모양 (흰 테두리, 접힌 모서리, 글 줄)
    w = max(2, int(12 * s))
    x0, y0, x1, y1, fold = 72 * s, 52 * s, 184 * s, 204 * s, 40 * s
    outline = [(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1), (x0, y0)]
    d.line(outline, fill="white", width=w, joint="curve")
    d.line([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill="white", width=max(2, w * 2 // 3), joint="curve")
    for i, yy in enumerate((112, 140, 168)):
        d.line([(100 * s, yy * s), ((156 if i < 2 else 136) * s, yy * s)], fill="white", width=w)
    return img


if __name__ == "__main__":
    big = draw(256)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    big.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("만듦:", OUT)
