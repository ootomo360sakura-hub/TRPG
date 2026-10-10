# TRPGプレイヤー募集Bot

Discordで卓のプレイヤーを募集するBot。記事にリアクションした人のメンションを記事内に自動で書き加え、
開催1週間前と前日には参加者へリマインドを送る。

## 使い方

### 募集する(GM)
1. `/募集` を実行 → フォームに **タイトル・定員**(必須)と募集内容(任意)を入力
2. カレンダーが表示されるので、プルダウン(1〜15日 / 16日〜月末)から **開催日を選択**(◀ ▶ で月を移動)
3. 開始時刻の入力欄が出るので `21:00`・`21時`・`2130` などで入力
4. 自分にだけ下書きプレビューが表示される
   - **📅 日時を変更**:カレンダーから選び直す
   - **📝 追加項目を入力**:システム / 推奨技能 / 想定プレイ時間 / 形式(ボイス/テキスト) / 備考(すべて任意。押したときだけ表示)
   - **🔔 リマインド: あり/なし**:押すたびに切り替わる
   - **📣 投稿する** でチャンネルに投稿
5. 投稿後は記事の **⚙️ GMメニュー**(投稿者本人のみ使える)から
   - ✏️ 内容を編集 / 📅 日時を変更 / 📝 追加項目を編集 / 🔔 リマインド切替 / 🗑️ 募集を取り消す(確認あり)

Discordのフォームには日付ピッカーがないため、カレンダー表示+日付のプルダウンで代用している。今日より前の日付は選べない。

### 参加する(プレイヤー)
| リアクション | 意味 |
|------|------|
| ✋ | 参加希望。記事の「参加希望」欄にメンションが載る |
| 👀 | 興味あり。記事の「興味あり」欄にメンションが載る |

リアクションを外すと欄から消える。

## 動作の詳細
- 記事には「※定員を超えた場合はGM判断となります。」と常に表示される
- 参加希望が定員に達すると **自動で締切**:タイトルが【満員・締切】になる。👀 興味ありは引き続き付けられる
- 締切後に付いた ✋ はBotでは外さず、「定員超過(GM判断)」欄に記載する(扱いはGMが判断)。参加希望者が抜けて空きが出たら自動で募集中に戻る
- GM本人とBotのリアクションは数えない
- **リマインド**(ありの場合):開催日の **7日前の午前9時** と **前日の午前9時** に、募集記事への返信で参加希望者とGMにメンション。
  投稿時点ですでに過ぎているタイミングの分は送らない。開催日時を変更するとリマインドも新しい日時に合わせ直す
- **取消**:記事が【募集取消】になり、参加希望者に取消のお知らせを送る
- 募集データは SQLite(`data/recruit.db`)に保存。Botを再起動しても募集・ボタン・リマインドは引き継がれる

## Discord側の準備
1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリを作成し、「Bot」タブでトークンを発行
   (特権インテントはどれもONにしなくてよい)
2. 「OAuth2 → URL Generator」で scope に `bot` と `applications.commands`、Bot Permissions に以下を選び、生成したURLでサーバーに招待
   - View Channels / Send Messages / Embed Links / Add Reactions / Read Message History

## サーバーで常時稼働させる

無料で常時稼働させる候補の比較と、Google Cloud(e2-micro)での詳しい手順は **[HOSTING.md](HOSTING.md)** を参照。

### Docker(推奨)
Dockerが入ったLinuxサーバー(VPSなど)で:

```bash
git clone <このリポジトリ> && cd TRPG/discord_bot
cp .env.example .env      # DISCORD_TOKEN を書き込む
docker compose up -d --build
docker compose logs -f    # 「ログインしました」と出ればOK
```

`restart: unless-stopped` により、Botが落ちたりサーバーが再起動しても自動で立ち上がる。
更新は `git pull && docker compose up -d --build`。

### systemd(Dockerを使わない場合)
```bash
cd /opt/TRPG/discord_bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # DISCORD_TOKEN を書き込む
sudo cp trpg-recruit-bot.service /etc/systemd/system/   # User とパスを環境に合わせて編集
sudo systemctl enable --now trpg-recruit-bot
journalctl -u trpg-recruit-bot -f
```

## 開発
```bash
pip install -r requirements.txt pytest
python3 -m pytest tests   # Discordに接続しないロジックのテスト
python3 bot.py            # .env の GUILD_ID を入れておくとコマンドが即時反映される
```

`backup/` には仕様変更前のファイルを日時ごとに保存している。
