# TRPGプレイヤー募集Bot

Discordで卓のプレイヤーを募集するBot。参加希望者は募集記事に ✋ リアクションを付けるだけで、
記事内の「参加者」欄にその人のメンションが自動で書き加えられる。

## 機能(v1)

| 操作 | 内容 |
|------|------|
| `/募集` | 募集記事を投稿。`タイトル` `定員` は必須、`日時` `システム` `詳細` は任意 |
| ✋ リアクションを付ける | 参加者欄に自分のメンションが追加される |
| ✋ リアクションを外す | 参加者欄から削除される(補欠がいれば繰り上がる) |
| 記事を右クリック → アプリ → `募集を締め切る` | 締切状態にする(GM本人 or メッセージ管理権限を持つ人のみ) |

- 定員を超えた人は「補欠」欄にリアクション順で並ぶ
- 満員になると記事の色がオレンジ、締切後はグレーになる
- GM(募集者)本人とBotのリアクションは参加者として数えない
- 募集の状態は記事のEmbed自体に保存しているので、Botを再起動しても既存の募集はそのまま動く
- 参加者欄はEmbed内なので、メンションが付いても通知は飛ばない

## セットアップ

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリを作成し、
   「Bot」タブでトークンを発行する(特権インテントはどれもONにしなくてよい)
2. 「OAuth2 → URL Generator」で scope に `bot` と `applications.commands`、
   Bot Permissions に以下を選び、生成したURLでサーバーに招待する
   - View Channels / Send Messages / Embed Links / Add Reactions / Read Message History
3. 起動する

```bash
cd discord_bot
pip install -r requirements.txt
cp .env.example .env   # DISCORD_TOKEN を書き込む(GUILD_ID も入れるとコマンドが即時反映される)
python3 bot.py
```

`GUILD_ID` を空にするとグローバルコマンドとして登録される(全サーバーへの反映に時間がかかることがある)。
