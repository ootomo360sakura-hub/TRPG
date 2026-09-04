# TRPG漫画作成プロジェクト

コマ割りデータを収集・管理し、それを参照してAI画像生成でセリフ入りの1ページ漫画を作るリポジトリ。

## 仕組み

```
vault/(Obsidianボールト: コマ割りデータ収集・管理)
  │  python3 tools/build_layouts.py
  ▼
data/layouts.json(コマ割り定義のコンパイル結果)
  │
  │  episodes/epNNN/script.yaml(台本: レイアウトID+セリフ+コマ内容)
  │  Higgsfieldでコマ画像を生成 → episodes/epNNN/panels/
  ▼
tools/compose_page.py
  ▼
episodes/epNNN/page_1.png(コマ割り+ワク線+縦書き吹き出し入りの完成ページ)
```

漫画を作る具体的な手順は **`.claude/skills/manga-create/SKILL.md`** にスキル化してある。
Claude Codeに「漫画を作って」と頼むとこの手順で作成される。

## ディレクトリ

| パス | 内容 |
|------|------|
| `vault/` | Obsidianで開くボールト。コマ割りノート(YAMLフロントマター)と漫画理論の知識ノート |
| `vault/コマ割り/` | レイアウトデータ本体。1ノート=1レイアウト |
| `vault/知識/` | 視線誘導・吹き出し作法などの理論ノート(NotebookLMソースの元) |
| `vault/テンプレート/` | 新規コマ割り収集用テンプレート |
| `notebooklm/` | NotebookLMアップロード用の結合Markdown(自動生成) |
| `data/layouts.json` | ボールトからコンパイルしたコマ割り定義(自動生成) |
| `tools/` | パイプラインスクリプト |
| `episodes/` | エピソードごとの台本・コマ画像・完成ページ |
| `scenarios/` | TRPGシナリオ本体（卓で使うGM資料一式） |

## ツール

```bash
pip install pillow pyyaml

python3 tools/build_layouts.py              # vault → data/layouts.json
python3 tools/export_notebooklm.py          # vault → notebooklm/*.md
python3 tools/compose_page.py episodes/ep001  # 台本+コマ画像 → page_1.png
```

## コマ割りデータの収集・管理(Obsidian × NotebookLM)

1. **Obsidian**: このリポジトリの `vault/` をボールトとして開く。
   新しいコマ割りパターンは `vault/テンプレート/コマ割り収集テンプレート.md` を複製して
   `vault/コマ割り/` に追加し、`build_layouts.py` でコンパイルする
2. **NotebookLM**: `tools/export_notebooklm.py` の出力(`notebooklm/`)を
   NotebookLMの「ソースを追加」で取り込み、コマ割り研究・要約・質問に使う。
   得られた知見は `vault/知識/` に還元する(NotebookLMは公開APIがないため手動取り込み)

## シナリオ

漫画パイプラインとは別に、卓で実際に回すためのTRPGシナリオを `scenarios/` に置いている。

| シナリオ | システム | 内容 |
|----------|----------|------|
| [`arianrhod2e_魔石回廊/`](scenarios/arianrhod2e_魔石回廊/) | アリアンロッドRPG 2E | ダンジョンハック。魔石を台座にセットして戦闘マップ上に「2倍」の反応エリアを作り、重ねて戦う |

## 補足

- コマ画像の生成はHiggsfield MCP(`nano_banana_pro`、白黒漫画スタイル指定)を使用
- リモート開発環境ではHiggsfield CDNへの直接ダウンロードがネットワークポリシーで
  ブロックされるため、`.github/workflows/fetch-assets.yml`(手動実行)が
  `assets.json` 記載のURLをダウンロードしてブランチにコミットする
