#!/usr/bin/env python3
"""コマ割りデータ(data/layouts.json)とエピソード台本(script.yaml)から、
パネル画像を合成して吹き出し(縦書きセリフ)入りの漫画ページを生成する。

使い方:
    python3 tools/compose_page.py episodes/ep001
出力:
    episodes/ep001/page_1.png
"""
import json
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS = ROOT / "data" / "layouts.json"

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]

# 縦書きで90度回転して描く文字(縦書き専用グリフを持たないフォント向け)
ROTATE_CHARS = set("ー−〜~…()「」『』[]<>")
# 右上に寄せて描く句読点
PUNCT_SHIFT = {"、", "。"}
# 行頭(列頭)に置かない文字 → 前の列末尾に送る
KINSOKU_HEAD = set("、。,.!?!?・ー〜…っゃゅょァィゥェォッ」』)]")


def find_font(size):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("日本語フォントが見つかりません。FONT_CANDIDATESに追記してください。")


def wrap_vertical(text, max_chars):
    """テキストを縦書きの列(右→左)に分割し、行頭禁則を適用する。"""
    cols, col = [], []
    for ch in text:
        if ch == "\n":
            cols.append(col)
            col = []
            continue
        col.append(ch)
        if len(col) >= max_chars:
            cols.append(col)
            col = []
    if col:
        cols.append(col)
    # 行頭禁則: 列頭の句読点等を前の列末尾へ送る
    for i in range(1, len(cols)):
        while cols[i] and cols[i][0] in KINSOKU_HEAD:
            cols[i - 1].append(cols[i].pop(0))
    return [c for c in cols if c]


def rotated_glyph(ch, font, size):
    """文字を90度時計回りに回転したタイル画像を返す(長音・括弧・三点リーダ用)。"""
    tile = Image.new("RGBA", (int(size * 1.5), int(size * 1.5)), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    bbox = d.textbbox((0, 0), ch, font=font)
    d.text(
        ((tile.width - (bbox[2] - bbox[0])) / 2 - bbox[0],
         (tile.height - (bbox[3] - bbox[1])) / 2 - bbox[1]),
        ch, font=font, fill="black",
    )
    return tile.rotate(-90, resample=Image.BICUBIC)


def draw_vertical_text(img, draw, cx, cy, cols, font, size, fill="black"):
    """列リストを中心(cx, cy)に縦書き描画する。列は右→左。"""
    line_h = int(size * 1.18)
    col_w = int(size * 1.25)
    total_w = col_w * len(cols)
    max_len = max(len(c) for c in cols)
    total_h = line_h * max_len
    x0 = cx + total_w / 2 - col_w / 2  # 最初の列は一番右
    y0 = cy - total_h / 2
    for i, col in enumerate(cols):
        x = x0 - i * col_w
        for j, ch in enumerate(col):
            y = y0 + j * line_h
            if ch in ROTATE_CHARS:
                tile = rotated_glyph(ch, font, size)
                img.paste(fill, (int(x - tile.width / 2), int(y + size / 2 - tile.height / 2)), tile)
            elif ch in PUNCT_SHIFT:
                draw.text((x + size * 0.35, y - size * 0.30), ch, font=font, fill=fill)
            else:
                bbox = draw.textbbox((0, 0), ch, font=font)
                w = bbox[2] - bbox[0]
                draw.text((x - w / 2, y), ch, font=font, fill=fill)
    return total_w, total_h


def bubble_geometry(cols, size):
    line_h = int(size * 1.18)
    col_w = int(size * 1.25)
    tw = col_w * len(cols)
    th = line_h * max(len(c) for c in cols)
    # 楕円は内接テキストより一回り大きく
    return int(tw * 1.9) + 24, int(th * 1.35) + 24


def draw_tail(draw, bx, by, bw, bh, direction):
    """吹き出しのしっぽ。direction: down-left / down-right / up-left / up-right"""
    cx, cy = bx + bw / 2, by + bh / 2
    dx = -1 if "left" in direction else 1
    dy = 1 if "down" in direction else -1
    base_x = cx + dx * bw * 0.18
    base_y = cy + dy * bh * 0.42
    tip = (cx + dx * bw * 0.55, cy + dy * bh * 0.75)
    p1 = (base_x - dx * bw * 0.10, base_y)
    p2 = (base_x + dx * bw * 0.10, base_y - dy * bh * 0.06)
    draw.polygon([p1, p2, tip], fill="white", outline="black", width=3)
    # 楕円との継ぎ目の線を消す
    draw.polygon([p1, p2, tip], fill="white")
    draw.line([p1, tip], fill="black", width=3)
    draw.line([p2, tip], fill="black", width=3)


def draw_bubble(img, draw, panel_rect, dialogue, font, size):
    px, py, pw, ph = panel_rect
    text = dialogue["text"]
    max_chars = int(dialogue.get("max_chars", 7))
    cols = wrap_vertical(text, max_chars)
    bw, bh = bubble_geometry(cols, size)
    # パネル内の相対位置(デフォルトは右上)
    rx = float(dialogue.get("bx", 0.78))
    ry = float(dialogue.get("by", 0.30))
    cx = px + pw * rx
    cy = py + ph * ry
    bx, by = cx - bw / 2, cy - bh / 2
    # パネルからはみ出しすぎないよう調整
    bx = max(px - bw * 0.15, min(bx, px + pw - bw * 0.85))
    by = max(py - bh * 0.10, min(by, py + ph - bh * 0.90))
    cx, cy = bx + bw / 2, by + bh / 2

    shape = dialogue.get("shape", "normal")
    if shape == "narration":
        draw.rectangle([bx, by, bx + bw, by + bh], fill="white", outline="black", width=3)
    elif shape == "shout":
        import math
        pts = []
        n = 22
        for i in range(n * 2):
            ang = math.pi * i / n
            r_w = bw / 2 * (1.0 if i % 2 == 0 else 0.78)
            r_h = bh / 2 * (1.0 if i % 2 == 0 else 0.78)
            pts.append((cx + r_w * math.cos(ang), cy + r_h * math.sin(ang)))
        draw.polygon(pts, fill="white", outline="black", width=3)
    else:
        if dialogue.get("tail"):
            draw_tail(draw, bx, by, bw, bh, dialogue["tail"])
        draw.ellipse([bx, by, bx + bw, by + bh], fill="white", outline="black", width=3)

    draw_vertical_text(img, draw, cx, cy, cols, font, size)


def cover_fit(img, w, h):
    """アスペクト比を保ってコマを覆うよう拡大し、中央でクロップする。"""
    scale = max(w / img.width, h / img.height)
    nw, nh = int(img.width * scale + 0.5), int(img.height * scale + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def compose(episode_dir: Path):
    script = yaml.safe_load((episode_dir / "script.yaml").read_text(encoding="utf-8"))
    layouts = json.loads(LAYOUTS.read_text(encoding="utf-8"))
    layout = layouts[script["layout"]]

    page_cfg = layout["page"]
    W, H = page_cfg["width"], page_cfg["height"]
    margin = page_cfg.get("margin", 50)
    gx = page_cfg.get("gutter_x", page_cfg.get("gutter", 24))
    gy = page_cfg.get("gutter_y", page_cfg.get("gutter", 24))
    inner_w, inner_h = W - margin * 2, H - margin * 2

    page = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(page)
    font_size = int(script.get("font_size", 30))
    font = find_font(font_size)

    panels = script["panels"]
    geoms = sorted(layout["panels"], key=lambda p: p["index"])
    if len(panels) != len(geoms):
        raise SystemExit(
            f"台本のコマ数({len(panels)})がレイアウト{script['layout']}のコマ数({len(geoms)})と一致しません"
        )

    rects = []
    for geom, panel in zip(geoms, panels):
        x = margin + geom["x"] * inner_w + gx / 2
        y = margin + geom["y"] * inner_h + gy / 2
        w = geom["w"] * inner_w - gx
        h = geom["h"] * inner_h - gy
        x, y, w, h = int(x), int(y), int(w), int(h)
        rects.append((x, y, w, h))
        img_path = episode_dir / panel["image"]
        if img_path.exists():
            img = cover_fit(Image.open(img_path).convert("RGB"), w, h)
            page.paste(img, (x, y))
        else:
            draw.rectangle([x, y, x + w, y + h], fill="#eeeeee")
            print(f"警告: 画像なし {img_path}", file=sys.stderr)
        draw.rectangle([x, y, x + w, y + h], outline="black", width=4)

    # 画像を貼り終えてから吹き出しを重ねる
    for rect, panel in zip(rects, panels):
        for dlg in panel.get("dialogues", []):
            draw_bubble(page, draw, rect, dlg, font, font_size)

    out = episode_dir / "page_1.png"
    page.save(out)
    print(f"生成: {out}")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("使い方: python3 tools/compose_page.py episodes/<エピソード>")
    compose(Path(sys.argv[1]).resolve())
