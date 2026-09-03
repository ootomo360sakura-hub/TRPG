"""デスクトップショートカット用のアイコン(lanshare.ico)を生成する。

外部ライブラリを使わずにRGBAのPNGを描き、それをICOコンテナに詰める
(Windows 10以降はPNG形式を含むICOをそのまま扱える)。
図柄は「上下の矢印=双方向の転送」を角丸の四角に載せたもの。

    python3 lanshare/assets/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4

TOP = (17, 138, 153)      # 明るいティール
BOTTOM = (10, 99, 115)    # 暗いティール
GLYPH = (255, 255, 255)


def _rounded_square(x: float, y: float, radius: float, pad: float) -> bool:
    """0〜1座標が角丸の四角の内側かどうか。"""
    left = top = pad
    right = bottom = 1.0 - pad
    if not (left <= x <= right and top <= y <= bottom):
        return False
    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 or (
        left + radius <= x <= right - radius or top + radius <= y <= bottom - radius
    )


def _in_triangle(px: float, py: float, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign((px, py), a, b)
    d2 = sign((px, py), b, c)
    d3 = sign((px, py), c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _in_rect(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> bool:
    return x0 <= px <= x1 and y0 <= py <= y1


def _glyph(x: float, y: float) -> bool:
    """上向き矢印(左)と下向き矢印(右)。双方向の転送を表す。"""
    up = _in_rect(x, y, 0.305, 0.40, 0.395, 0.75) or _in_triangle(
        x, y, (0.35, 0.235), (0.225, 0.44), (0.475, 0.44)
    )
    down = _in_rect(x, y, 0.605, 0.25, 0.695, 0.60) or _in_triangle(
        x, y, (0.65, 0.765), (0.525, 0.56), (0.775, 0.56)
    )
    return up or down


def render(size: int) -> bytes:
    """size×sizeのRGBA画素列(1画素4バイト)を返す。"""
    scale = size * SUPERSAMPLE
    radius = 0.22
    pad = 0.03
    samples = SUPERSAMPLE * SUPERSAMPLE
    rows = bytearray()
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    fx = (px * SUPERSAMPLE + sx + 0.5) / scale
                    fy = (py * SUPERSAMPLE + sy + 0.5) / scale
                    if not _rounded_square(fx, fy, radius, pad):
                        continue
                    if _glyph(fx, fy):
                        color = GLYPH
                    else:
                        t = (fy - pad) / (1 - 2 * pad)
                        color = tuple(
                            round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)
                        )
                    r += color[0]
                    g += color[1]
                    b += color[2]
                    a += 255
            if a == 0:
                row += b"\x00\x00\x00\x00"
            else:
                covered = a // 255
                row += bytes((r // covered, g // covered, b // covered, a // samples))
        rows += row
    return bytes(rows)


def to_png(pixels: bytes, size: int) -> bytes:
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw += b"\x00" + pixels[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def build_ico(sizes=SIZES) -> bytes:
    images = [to_png(render(size), size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, image in zip(sizes, images):
        entries += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset
        )
        offset += len(image)
    return header + entries + b"".join(images)


def main() -> None:
    target = Path(__file__).with_name("lanshare.ico")
    target.write_bytes(build_ico())
    preview = Path(__file__).with_name("lanshare-256.png")
    preview.write_bytes(to_png(render(256), 256))
    print(f"{target} ({target.stat().st_size:,} バイト) / プレビュー: {preview.name}")


if __name__ == "__main__":
    main()
