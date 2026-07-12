# 本番素材のHiggsfield生成プロンプト集

参考動画: https://www.youtube.com/watch?v=HSPQoox0mRo
(かみかぜ氏のMV作例デモ「竜宮ワンダーランド」の下準備フォルダを再現する)

現在フォルダに入っている画像はローカル生成のサンプル(プレースホルダ)。
クレジットをチャージ後、以下のプロンプトでHiggsfield MCPから本番素材を生成して差し替える。

## コスト見積もり(2026-07-12時点)

| 素材 | モデル | クレジット |
|------|--------|-----------|
| ref_a.png | nano_banana_pro (1k, 3:4) | 2 |
| ref_b.png | nano_banana_pro (1k, 3:4) | 2 |
| mic.png | nano_banana_pro | 2 |
| ヘッドホン_ロゴなし.png | nano_banana_pro | 2 |
| テスト動画(5秒) | kling3_0_turbo | 7.5 |
| **合計** | | **15.5** |

※残高0のため要チャージ。`balance` ツールで確認できる。

## ref_a.png — 女性ボーカル 三面図

- model: `nano_banana_pro`(または `soul_2`)
- aspect_ratio: `4:3`

```
Character reference sheet of a young Japanese female vocalist, three full-body
views side by side (front view, side view, back view), same character in all
views. Black bob haircut with blunt bangs, all-black outfit: oversized black
jacket, black wide-leg trousers. Neutral standing pose, arms relaxed.
Clean plain white background, soft even studio lighting, photorealistic,
fashion lookbook style. No text, no logos.
```

## ref_b.png — 男性ギタリスト 三面図

- model: `nano_banana_pro`(または `soul_2`)
- aspect_ratio: `4:3`

```
Character reference sheet of a young Japanese male guitarist, three full-body
views side by side (front view holding an acoustic guitar, side view, back
view), same character in all views. Short black hair, all-black outfit:
black shirt, black wide trousers. Natural acoustic guitar with warm wood
finish. Clean plain white background, soft even studio lighting,
photorealistic, fashion lookbook style. No text, no logos.
```

## mic.png — マイクスタンド

- model: `nano_banana_pro`
- aspect_ratio: `3:4`

```
Product photo of a professional studio microphone on a black boom mic stand
with tripod base, isolated on a pure white background, soft studio lighting,
subtle shadow, photorealistic, high detail. No text, no logos, no people.
```

## ヘッドホン_ロゴなし.png — ヘッドホン

- model: `nano_banana_pro`
- aspect_ratio: `1:1`

```
Product photo of black professional over-ear studio monitor headphones with
coiled cable, completely logo-free plain design, isolated on a pure white
background, soft studio lighting, subtle shadow, photorealistic, high detail.
No text, no logos, no branding.
```

## テスト動画 — ボーカルカット(5秒)

- model: `kling3_0_turbo`(1枚の開始フレームから高速生成)
  キャラの同一性を重視するなら `seedance_2_0`
- medias: ref_a の生成job_idを `start_image` ロールで渡す
- duration: 5 / aspect_ratio: 16:9

```
The female vocalist sings emotionally into a studio microphone, close-up,
gentle camera push-in, cinematic lighting with deep blue underwater-like
ambience, music video aesthetic.
```

## 楽曲(竜宮ワンダーランド.wav)について

Higgsfield MCPは単体の音楽生成に対応していない(音声=スピーチのみ)。
本番の楽曲はSuno / Udio等の音楽生成サービスか既存音源を用意すること。
現在の `竜宮ワンダーランド.wav` はスクリプト合成のデモ音源。

## Higgsfield.png について

参考動画のフォルダにあった `Higgsfield.png` はサービスのロゴ画像
(デモのオーバーレイ用)なので、このプロジェクトでは作成対象外。

## 生成後の取り込み手順

1. 生成結果のCDN URLを `assets.json` に追記する(episodes/と同形式)
2. GitHub Actionsの `fetch-assets` ワークフローを
   `mv/竜宮ワンダーランドMV_作例デモ` を入力にして手動実行する
   (リモート開発環境からはCDNへ直接アクセスできないため)
