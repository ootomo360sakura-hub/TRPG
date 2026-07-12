#!/usr/bin/env python3
"""MV作例デモ用のサンプル素材(プレースホルダ)を生成する。

参考動画(https://www.youtube.com/watch?v=HSPQoox0mRo)の下準備フォルダと
同じ構成の素材一式を、Higgsfieldを使わずローカルで仮生成する:

  mv/竜宮ワンダーランドMV_作例デモ/
    ref_a.png                  女性ボーカルのキャラ三面図(サンプル)
    ref_b.png                  男性ギタリストのキャラ三面図(サンプル)
    mic.png                    マイクスタンド 白背景(サンプル)
    ヘッドホン_ロゴなし.png      ヘッドホン 白背景(サンプル)
    竜宮ワンダーランド.wav       デモ楽曲(合成音)
    テスト動画.mp4              素材スライドショーのテスト動画

本番素材はHiggsfieldで生成して差し替える(同フォルダの prompts.md を参照)。

usage: python3 tools/make_sample_materials.py [出力ディレクトリ]
"""
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]

INK = (30, 30, 34)
GRAY = (120, 120, 128)


def find_font(size):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("日本語フォントが見つかりません。FONT_CANDIDATESに追記してください。")


def label(draw, xy, text, size=28, fill=GRAY, anchor="mm"):
    draw.text(xy, text, font=find_font(size), fill=fill, anchor=anchor)


def person(draw, cx, base_y, h, view, hair="long", fill=INK):
    """棒人間より少し情報量のある人物シルエット。view: front/side/back"""
    head_r = h * 0.09
    head_cy = base_y - h + head_r
    torso_top = head_cy + head_r * 1.2
    torso_bot = base_y - h * 0.45
    hip_w = h * 0.13 if view != "side" else h * 0.09
    sh_w = h * 0.17 if view != "side" else h * 0.10

    # 髪
    if hair == "long":
        draw.ellipse([cx - head_r * 1.25, head_cy - head_r * 1.15,
                      cx + head_r * 1.25, head_cy + head_r * 2.6], fill=fill)
    else:
        draw.ellipse([cx - head_r * 1.15, head_cy - head_r * 1.15,
                      cx + head_r * 1.15, head_cy + head_r * 0.9], fill=fill)
    # 顔(正面のみ肌色の楕円を残す)
    if view == "front":
        draw.ellipse([cx - head_r * 0.85, head_cy - head_r * 0.6,
                      cx + head_r * 0.85, head_cy + head_r], fill=(228, 205, 190))
    # 胴体(黒衣装)
    draw.polygon([(cx - sh_w, torso_top), (cx + sh_w, torso_top),
                  (cx + hip_w, torso_bot), (cx - hip_w, torso_bot)], fill=fill)
    # 腕
    arm_w = h * 0.035
    for sx in (-1, 1) if view != "side" else (1,):
        draw.line([(cx + sx * sh_w * 0.9, torso_top + h * 0.02),
                   (cx + sx * (sh_w + arm_w), torso_bot - h * 0.02)],
                  fill=fill, width=int(arm_w * 2))
    # 脚(ワイドパンツ)
    leg_w = h * 0.055
    for sx in (-1, 1):
        draw.polygon([(cx + sx * hip_w * 0.15, torso_bot),
                      (cx + sx * hip_w, torso_bot),
                      (cx + sx * (hip_w + leg_w * 0.3), base_y),
                      (cx + sx * hip_w * 0.2, base_y)], fill=fill)


def guitar(draw, cx, cy, scale, fill=(150, 100, 60)):
    """斜めに構えたアコースティックギター(簡略)"""
    body_r = scale * 0.09
    draw.ellipse([cx - body_r, cy - body_r * 0.85, cx + body_r, cy + body_r * 0.85], fill=fill)
    draw.ellipse([cx - body_r * 0.35, cy - body_r * 0.35,
                  cx + body_r * 0.35, cy + body_r * 0.35], fill=(60, 40, 25))
    draw.line([(cx + body_r * 0.5, cy - body_r * 0.5),
               (cx + scale * 0.22, cy - scale * 0.18)], fill=fill, width=int(scale * 0.02))


def ref_sheet(path, title, hair, with_guitar):
    w, h = 1280, 960
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    ph = 560
    base_y = 780
    views = [("front", "正面"), ("side", "側面"), ("back", "背面")]
    for i, (view, name) in enumerate(views):
        cx = w * (0.22 + 0.28 * i)
        person(d, cx, base_y, ph, view, hair=hair)
        if with_guitar and view == "front":
            guitar(d, cx + ph * 0.02, base_y - ph * 0.42, ph)
        label(d, (cx, base_y + 50), name, size=30)
    label(d, (w / 2, 80), title, size=44, fill=INK)
    label(d, (w / 2, 900), "※サンプル(本番はHiggsfieldで生成した三面図に差し替え)", size=24)
    img.save(path)


def mic_image(path):
    w, h = 800, 1000
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    cx = w / 2
    # 三脚ベース
    for dx in (-140, 0, 140):
        d.line([(cx, 850), (cx + dx, 950)], fill=INK, width=14)
    # ポール
    d.line([(cx, 850), (cx, 300)], fill=INK, width=16)
    # ブームアーム
    d.line([(cx, 320), (cx + 170, 180)], fill=INK, width=12)
    # マイク本体
    d.rounded_rectangle([cx + 150, 90, cx + 210, 200], radius=28, fill=(70, 70, 78))
    d.ellipse([cx + 145, 60, cx + 215, 130], fill=(110, 110, 120))
    label(d, (w / 2, 985), "mic(サンプル)", size=26)
    img.save(path)


def headphones_image(path):
    w, h = 900, 800
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    cx, cy = w / 2, 430
    # ヘッドバンド
    d.arc([cx - 250, cy - 320, cx + 250, cy + 180], start=180, end=360, fill=INK, width=34)
    # イヤーカップ
    for sx in (-1, 1):
        x = cx + sx * 250
        d.rounded_rectangle([x - 70, cy - 90, x + 70, cy + 110], radius=60, fill=(45, 45, 52))
        d.rounded_rectangle([x - 44, cy - 62, x + 44, cy + 84], radius=44, fill=(90, 90, 100))
    # ケーブル
    d.arc([cx - 400, cy + 60, cx - 100, cy + 360], start=300, end=90, fill=INK, width=8)
    label(d, (w / 2, 760), "ヘッドホン ロゴなし(サンプル)", size=26)
    img.save(path)


def title_card(path, text, sub):
    w, h = 1920, 1080
    img = Image.new("RGB", (w, h), (12, 22, 46))  # 竜宮=深海の紺
    d = ImageDraw.Draw(img)
    for i in range(9):  # 泡
        x = 120 + i * 210
        y = 880 - (i % 4) * 160
        r = 12 + (i % 3) * 10
        d.ellipse([x - r, y - r, x + r, y + r], outline=(90, 140, 200), width=3)
    d.text((w / 2, h / 2 - 60), text, font=find_font(96), fill=(220, 235 , 255), anchor="mm")
    d.text((w / 2, h / 2 + 80), sub, font=find_font(40), fill=(140, 170, 210), anchor="mm")
    img.save(path)


def demo_track(path, seconds=20, rate=44100):
    """竜宮(海中)イメージの簡易デモ曲: ペンタトニックの琴風アルペジオ+パッド"""
    bpm = 90
    spb = 60 / bpm / 2  # 8分音符
    # Aマイナーペンタトニック
    scale = [220.0, 261.63, 293.66, 329.63, 392.0, 440.0, 523.25, 587.33]
    pattern = [0, 2, 4, 6, 7, 6, 4, 2, 1, 3, 5, 7, 6, 4, 3, 1]
    n = int(seconds * rate)
    samples = [0.0] * n

    def add_pluck(freq, t0, dur, vol):
        s0 = int(t0 * rate)
        for i in range(int(dur * rate)):
            if s0 + i >= n:
                break
            t = i / rate
            env = math.exp(-t * 3.5)
            v = math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(2 * math.pi * freq * 2 * t)
            samples[s0 + i] += v * env * vol

    t = 0.0
    k = 0
    while t < seconds - 1:
        add_pluck(scale[pattern[k % len(pattern)]], t, spb * 3, 0.28)
        if k % 8 == 0:  # 低音パッド
            add_pluck(scale[0] / 2, t, spb * 8, 0.22)
        t += spb
        k += 1
    # フェードイン/アウト
    fade = int(rate * 1.5)
    for i in range(fade):
        samples[i] *= i / fade
        samples[n - 1 - i] *= i / fade
    peak = max(abs(s) for s in samples) or 1.0
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(
            struct.pack("<h", int(s / peak * 32000)) for s in samples))


def make_video(out_dir, images_durations, audio, dest):
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"
    cmd = [ffmpeg, "-y"]
    filters = []
    for i, (img, dur) in enumerate(images_durations):
        cmd += ["-loop", "1", "-t", str(dur), "-i", str(out_dir / img)]
        filters.append(
            f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white,setsar=1,fps=30[v{i}]")
    cmd += ["-i", str(out_dir / audio)]
    concat = "".join(f"[v{i}]" for i in range(len(images_durations)))
    total = sum(d for _, d in images_durations)
    filters.append(f"{concat}concat=n={len(images_durations)}:v=1:a=0,"
                   f"fade=t=in:d=0.8,fade=t=out:st={total - 1}:d=1[v]")
    cmd += ["-filter_complex", ";".join(filters),
            "-map", "[v]", "-map", f"{len(images_durations)}:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(out_dir / dest)]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "mv/竜宮ワンダーランドMV_作例デモ")
    out_dir.mkdir(parents=True, exist_ok=True)

    ref_sheet(out_dir / "ref_a.png", "ref_a 女性ボーカル 三面図", "long", False)
    ref_sheet(out_dir / "ref_b.png", "ref_b 男性ギタリスト 三面図", "short", True)
    mic_image(out_dir / "mic.png")
    headphones_image(out_dir / "ヘッドホン_ロゴなし.png")
    title_card(out_dir / "_title.png", "竜宮ワンダーランド", "MV 作例デモ(テスト)")
    demo_track(out_dir / "竜宮ワンダーランド.wav")
    make_video(out_dir,
               [("_title.png", 3.5), ("ref_a.png", 4), ("ref_b.png", 4),
                ("mic.png", 3), ("ヘッドホン_ロゴなし.png", 3), ("_title.png", 2.5)],
               "竜宮ワンダーランド.wav", "テスト動画.mp4")
    print("done:", out_dir)


if __name__ == "__main__":
    main()
