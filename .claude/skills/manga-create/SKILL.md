---
name: manga-create
description: コマ割りされた1ページ漫画を作成する。vault/のコマ割りデータベースからレイアウトを選び、Higgsfieldでコマ画像を生成し、tools/compose_page.pyで吹き出し(縦書きセリフ)入りの漫画ページに合成する。「漫画を作って」「◯◯の4コマを描いて」などの依頼で使用。
---

# 漫画作成スキル

コマ割りデータ(Obsidianボールト)を参照して、セリフ入りの1ページ漫画を作る手順。

## 前提知識

- コマ割りデータは `vault/コマ割り/*.md`(YAMLフロントマター)で管理し、
  `python3 tools/build_layouts.py` で `data/layouts.json` にコンパイルする
- 演出理論は `vault/知識/コマ割りの基礎.md`・`vault/知識/吹き出しとセリフの作法.md` を参照
- 依存: `pip install pillow pyyaml`(日本語フォント必須。compose_page.pyのFONT_CANDIDATES参照)

## 手順

### 1. レイアウト選定

`data/layouts.json`(なければ `build_layouts.py` を実行)からレイアウトを選ぶ。

| 内容 | 推奨レイアウトID |
|------|-----------------|
| ギャグ・日常(起承転結) | `yonkoma_basic` |
| 会話劇・ストーリー | `standard_6` |
| 場面の導入・世界観提示 | `intro_page` |
| 見せ場・クライマックス | `climax_splash` |

合うものが無ければ `vault/テンプレート/コマ割り収集テンプレート.md` を元に
新しいコマ割りノートを `vault/コマ割り/` に追加してから再コンパイルする。

### 2. 台本作成

`episodes/ep00N/script.yaml` を作る(単一ページ=`episodes/ep001`、複数ページ=`episodes/ep002` が実例)。

- 単一ページはトップレベルに `layout:` と `panels:`
- 複数ページ(ストーリーもの)は `pages:` のリストにし、各要素に `layout:` と `panels:` を持たせる
  (出力は `page_1.png`, `page_2.png`, … になる)
- ページ構成の目安: 導入=`intro_page` → 展開=`standard_6` → 見せ場=`climax_splash`
- コマ数はレイアウトの `panels` 数と一致させる(不一致はエラーになる)
- 各コマ: `image`(相対パス)、`beat`(起承転結)、`description`(絵の内容)、`dialogues`
- セリフ(dialogue)のパラメータ:
  - `text`: セリフ本文(20文字以内推奨)
  - `bx`, `by`: 吹き出し中心のコマ内相対位置(0.0〜1.0)。読み順=右上→左下に配置
  - `max_chars`: 縦書き1列の文字数(5〜8が目安)
  - `shape`: `normal`(楕円)/ `shout`(ギザギザ)/ `narration`(四角)
  - `tail`: しっぽの向き `down-left` など(話者の口元へ向ける)

### 3. コマ画像生成(Higgsfield MCP)

**先に `mcp__Higgsfield__balance` で残高を確認する**(コマ数×約1〜2クレジット必要。
不足なら生成せず、ユーザーにチャージを依頼して中断ポイントを記録しておく)。

残高不足で生成に進めない間も、`episodes/ep00N/prompts.md` に全コマ分のプロンプト
(固定の人物描写・aspect_ratioを含む)を書き出しておくと、チャージ後すぐに
生成へ進める(`episodes/ep002/prompts.md` が実例)。

各コマを `mcp__Higgsfield__generate_image`(model: `nano_banana_pro`)で生成する。
プロンプトの約束事:

- 冒頭に固定: `Black and white Japanese manga panel, clean ink lines, screentone shading.`
- 末尾に固定: `No text, no speech bubbles, no lettering.`(吹き出しは後から合成するため)
- キャラクターの外見(髪型・服装・眼鏡など)を毎コマ同じ文言で書き、作画を安定させる
- `aspect_ratio` はコマの縦横比に近いものを選ぶ(4コマの横長コマ=16:9、
  縦長コマ=2:3、大ゴマ=4:3 など)

### 4. 画像のダウンロード

生成結果の `rawUrl` を `episodes/ep00N/assets.json` に記録する(形式はep001参照)。

- **通常環境**: `curl -o episodes/ep00N/panels/panelX.png "<rawUrl>"` で直接取得
- **CDNがネットワークポリシーで403になるリモート環境**: assets.jsonをコミット&プッシュし、
  GitHub Actionsの `fetch-assets` ワークフローを作業ブランチ指定で実行
  (`mcp__github__actions_run_trigger`, workflow: `fetch-assets.yml`,
  inputs: `{episode: episodes/ep00N}`)。完了後 `git pull` で取り込む

### 5. ページ合成

```bash
python3 tools/build_layouts.py          # レイアウトを変更した場合のみ
python3 tools/compose_page.py episodes/ep00N
```

`episodes/ep00N/page_1.png` にコマ割り・ワク線・吹き出し(縦書き)入りのページが出る。

### 6. 検品と調整

生成された `page_1.png` を必ずReadして確認する。チェック項目:

- 吹き出しがキャラクターの顔を隠していないか → `bx`/`by` を調整
- セリフが吹き出しからはみ出していないか → `max_chars` や `font_size` を調整
- 読み順(右上→左下)通りに吹き出しが並んでいるか

script.yamlを直して compose_page.py を再実行、を納得いくまで繰り返す。

### 7. 仕上げ

成果物(script.yaml, assets.json, panels/, page_1.png)をコミットする。
完成ページはSendUserFileでユーザーに送る。

## 収集・管理の運用(NotebookLM × Obsidian)

- 新しいコマ割りパターンを見つけたら `vault/コマ割り/` にノート追加 → `build_layouts.py`
- `python3 tools/export_notebooklm.py` で `notebooklm/` に結合Markdownを書き出し、
  NotebookLMに「ソースを追加」して調査・要約に使う(NotebookLMはAPI非公開のため手動取り込み)
- NotebookLMで得た知見は `vault/知識/` のノートに還元する
