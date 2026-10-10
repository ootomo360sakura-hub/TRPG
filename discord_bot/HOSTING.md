# 無料サーバーでBotを常時稼働させる手順

## 候補の比較

| 候補 | 料金 | 性能 | 向いているか | 注意点 |
|------|------|------|------|------|
| **Google Cloud e2-micro**(推奨) | 無料枠内なら0円 | 2vCPU(共有)/ メモリ1GB | ◎ このBotには十分 | 米国リージョン(オレゴン・アイオワ・サウスカロライナ)限定。クレジットカード登録が必要。ディスクを「標準永続ディスク」にしないと課金される |
| Oracle Cloud Always Free | 0円 | ARM 最大4コア / 24GB など | ○ 性能は最強 | カード登録が必要で審査に落ちることがある。東京・大阪は空きがなくVMを作れないことが多い。**負荷が低いVMは「アイドル」と判定されて停止されることがある**(Botは負荷が低いので該当しやすい。有料アカウントへの切替で回避できるが、手間とリスクが増える) |
| 自宅PC・ラズパイ | 電気代のみ | 機器しだい | △ | PCを24時間つけっぱなしにする必要がある。停電・再起動で止まる |
| 無料Botホスティング(Render・Replit など) | 0円 | ごく小さい | ✕ | 無料プランは一定時間アクセスがないとスリープするため、Botがオフラインになる。Railway・Herokuは無料枠が廃止済み |

**選定: Google Cloud の e2-micro。** このBotはメモリ100MB前後・CPUほぼ0で動き、
Discordとの通信量もわずかなので、無料枠に余裕で収まります。Oracleより登録・作成で失敗しにくく、
「アイドル停止」もありません。リージョンは米国になりますが、Discordのサーバー自体も主に米国にあるため問題ありません。

> 無料枠の条件は変わることがあります。作成前に [Google Cloud 無料枠の公式ページ](https://cloud.google.com/free/docs/free-cloud-features#compute) で
> 「e2-micro・対象リージョン・30GBの標準永続ディスク・月1GBの外向き通信」が今も対象かを確認してください。

---

## 手順(Google Cloud e2-micro)

### 1. Google Cloud の準備
1. <https://console.cloud.google.com/> にGoogleアカウントでログインし、利用規約に同意
2. 「お支払い」でクレジットカードを登録(無料枠の利用にも必要。無料トライアルのクレジットが付く場合もある)
3. 上部のプロジェクト選択 →「新しいプロジェクト」→ 名前を `trpg-bot` などにして作成
4. **予算アラートを設定**(念のため):「お支払い → 予算とアラート → 予算を作成」で金額を 100円 などにし、メール通知をON

### 2. VM(仮想サーバー)を作成
「Compute Engine → VMインスタンス」(初回は「APIを有効にする」を押す)→「インスタンスを作成」

| 項目 | 設定値 |
|------|------|
| 名前 | `trpg-bot` |
| リージョン | `us-west1`(オレゴン)・`us-central1`(アイオワ)・`us-east1`(サウスカロライナ)のどれか |
| マシンの構成 | シリーズ **E2** → マシンタイプ **e2-micro** |
| ブートディスク | 「変更」→ OS **Debian 12** / ディスクの種類 **標準永続ディスク** / サイズ **30GB** |
| ファイアウォール | HTTP・HTTPS はどちらもチェック不要(Botは外から接続を受けない) |

画面右側の月額見積もりに料金が表示されても、無料枠の分は請求時に差し引かれます。
ディスクの種類が「バランス永続ディスク」のままだと無料枠の対象外になるので注意してください。

「作成」を押し、一覧に表示されたら行の右側の **SSH** ボタンを押す(ブラウザでサーバーの操作画面が開く)。

### 3. サーバーにDockerを入れる
SSH画面で以下を1行ずつ実行:

```bash
sudo apt-get update && sudo apt-get install -y git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

一度SSH画面を閉じて、もう一度 **SSH** ボタンで開き直す(Dockerの権限を反映させるため)。

メモリ1GBでのビルドを安定させるため、スワップ(1GB)も作っておく:

```bash
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 4. Botのコードを取得
リポジトリが非公開なので、サーバー専用の読み取り用の鍵(デプロイキー)を登録する。

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

表示された `ssh-ed25519 ...` の1行をコピーし、GitHubのリポジトリ画面
「Settings → Deploy keys → Add deploy key」に貼り付けて保存(「Allow write access」はチェックしない)。

```bash
git clone git@github.com:ootomo360sakura-hub/TRPG.git
cd TRPG/discord_bot
```

> 開発中のブランチを使う場合は、clone後に `git checkout claude/discord-trpg-recruitment-bot-ih78vc` を実行。
> mainにマージ済みならそのままでOK。

### 5. 設定して起動

```bash
cp .env.example .env
nano .env
```

`DISCORD_TOKEN=` の後ろにBotのトークンを貼り付け、`GUILD_ID=` に使うDiscordサーバーのIDを入れて保存
(Ctrl+O → Enter → Ctrl+X)。サーバーIDは、Discordの設定で開発者モードをONにし、サーバー名を右クリック →「IDをコピー」で取得できる。

```bash
docker compose up -d --build
docker compose logs -f
```

`ログインしました: ...` と表示されたら成功(Ctrl+C でログ表示を終了しても、Botは動き続ける)。
Discordで `/募集` が使えることを確認する。

---

## 運用

| やりたいこと | コマンド(`TRPG/discord_bot` で実行) |
|------|------|
| 状態を確認 | `docker compose ps` |
| ログを見る | `docker compose logs -f --tail 100` |
| コードを更新して再起動 | `git pull && docker compose up -d --build` |
| 再起動 | `docker compose restart` |
| 停止 | `docker compose down` |
| 募集データのバックアップ | `cp data/recruit.db ~/recruit_$(date +%Y%m%d_%H%M%S).db` |

- Botが落ちたりVMが再起動しても、Dockerが自動で起動し直す(`restart: unless-stopped`)
- 募集データ(リマインド予定を含む)は `data/recruit.db` にある。VMを作り直すときはこのファイルを退避しておく
- トークンが漏れた場合は、Developer Portal で「Reset Token」してから `.env` を書き換え、`docker compose up -d` で再起動する
