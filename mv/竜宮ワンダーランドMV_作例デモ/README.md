# 竜宮ワンダーランドMV 作例デモ(素材フォルダ)

参考動画 https://www.youtube.com/watch?v=HSPQoox0mRo の下準備フォルダと
同じ構成で素材データを揃えたもの。まずはローカル生成のサンプル画像で
テスト動画まで組み立ててあり、本番はHiggsfieldで生成した素材に差し替える。

## 構成(参考動画のフォルダとの対応)

| ファイル | 参考動画での役割 | 現状 |
|----------|------------------|------|
| `ref_a.png` | 女性ボーカルのキャラ参照(三面図) | サンプル(Pillow描画) |
| `ref_b.png` | 男性ギタリストのキャラ参照(三面図) | サンプル(Pillow描画) |
| `mic.png` | マイクスタンド 白背景 | サンプル(Pillow描画) |
| `ヘッドホン_ロゴなし.png` | ヘッドホン 白背景 | サンプル(Pillow描画) |
| `竜宮ワンダーランド.wav` | 楽曲(20秒) | サンプル(スクリプト合成音) |
| `テスト動画.mp4` | — | サンプル素材のスライドショー(20秒 1080p 音声付き) |
| `_title.png` | — | テスト動画用タイトルカード |
| `prompts.md` | — | 本番素材のHiggsfield生成プロンプト+コスト |
| `assets.json` | — | 生成URLの取り込み定義(fetch-assetsワークフロー用) |
| (Higgsfield.png) | サービスロゴ(デモ用オーバーレイ) | 対象外 |

## 再生成

```bash
pip install pillow imageio-ffmpeg
python3 tools/make_sample_materials.py "mv/竜宮ワンダーランドMV_作例デモ"
```

## 本番素材への差し替え手順

1. Higgsfieldのクレジットをチャージ(全素材+テスト動画5秒で約15.5クレジット)
2. `prompts.md` のプロンプトで生成
3. 生成結果のURLを `assets.json` に記入し、GitHub Actionsの
   `fetch-assets` ワークフローをこのディレクトリを入力にして手動実行
4. 楽曲はHiggsfieldでは生成不可のため、Suno/Udio等で用意して差し替え
