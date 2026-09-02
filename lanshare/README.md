# LANファイル共有(Windows PC ⇄ iPhone)

同じWi-Fi(ルーター)につながっているWindows PCとiPhoneの間で、
**クラウドを経由せず**ファイルとテキストをやり取りするためのアプリ。

PC側でサーバを起動し、iPhoneはSafariでURLを開くだけ。
iPhone側にアプリのインストールは不要(App Store未使用)で、外部ライブラリも使わない
(Python標準ライブラリのみ。QRコード生成も自前実装)。

```
  Windows PC                         iPhone
 ┌───────────────┐   同じWi-Fi   ┌──────────────┐
 │ python -m lanshare │◀────────────▶│ Safariで開く  │
 │  ├ shared/     │  HTTP/LAN内   │  ・写真/動画を送る│
 │  ├ _backup/    │               │  ・PCのファイルを保存│
 │  └ _trash/     │               │  ・テキスト共有   │
 └───────────────┘               └──────────────┘
```

## できること

| 機能 | 説明 |
|------|------|
| iPhone → PC | 写真・動画・書類をまとめてアップロード(複数同時、進捗バー付き) |
| PC → iPhone | 一覧からタップしてプレビュー、「保存」で"ファイル"アプリや写真に保存 |
| PC → PC | ブラウザ画面へのドラッグ&ドロップでアップロード |
| テキスト共有 | URLやメモをPC⇄iPhoneでコピー&ペースト |
| QRコード | PCの画面(またはコンソール)のQRを読むだけでPIN入力なしに接続 |
| 動画の途中再生 | Rangeリクエスト対応。大きな動画のシークや再開ができる |

## 必要なもの

- Windows PC に Python 3.9 以上(3.11以上を推奨)
  - インストール時に **「Add python.exe to PATH」にチェック**
- PCとiPhoneが**同じWi-Fi(同じルーター)**に接続されていること
- 追加パッケージのインストールは不要

## 起動

### いちばん簡単な方法

`lanshare\start-server.bat` をダブルクリック。
リポジトリ直下の `shared` フォルダが共有フォルダになり、PCのブラウザが自動で開く。

### コマンドから

```bat
cd C:\path\to\TRPG
python -m lanshare                          :: ./shared を共有
python -m lanshare --dir "D:\受け渡し"       :: フォルダを指定
python -m lanshare --port 8080              :: ポートを変更
python -m lanshare --on-conflict backup     :: 同名ファイルは日時バックアップを残して上書き
```

起動するとコンソールに接続先URL・PIN・QRコードが表示される。

```
========================================================
  LANファイル共有サーバを起動しました
========================================================
  共有フォルダ : C:\path\to\TRPG\shared
  接続先URL    : http://192.168.1.23:8765/
  PIN          : 418205
```

## iPhoneからの使い方

1. iPhoneを**PCと同じWi-Fi**につなぐ
2. 次のどちらかで開く
   - **QRコード**: コンソール(または画面の「接続情報」タブ)のQRをカメラで読み取る → PIN入力なしで開く
   - **手入力**: Safariのアドレス欄に `http://192.168.1.23:8765` と入力し、PINを入力
3. 「ファイルを選ぶ」で写真・動画・書類を選んで送信(複数可)
4. PCから受け取るときは一覧の「保存」→ "ファイル"アプリなどに保存

> **ヒント**: Safariの共有ボタンから「ホーム画面に追加」しておくと、
> 次回からアプリのように1タップで開ける。

## 安全のための既定動作

このアプリはPC内のファイルを操作するため、既定値は安全側に倒してある。

| 項目 | 既定の動作 | 変更するオプション |
|------|-----------|------------------|
| 認証 | 起動ごとに6桁PINを自動生成。セッションCookieで12時間有効 | `--pin` で固定 / `--no-auth` で無効化 |
| 接続元 | プライベートIP(LAN内)からのみ許可 | `--allow-any-client` |
| **削除** | `_trash/日時/` へ移動するだけで、実ファイルは残る。UIでも「PC内のファイルを削除します」と確認ダイアログを表示 | `--hard-delete` で即時削除(復元不可) |
| **同名ファイル** | 上書きせず別名(`memo (1).txt`)で保存 | `--on-conflict backup` で `_backup/memo.20260902-235118.txt` に退避してから上書き |
| ファイル名 | Windowsで使えない文字・予約名・パス区切りを除去(`../` によるフォルダ外書き込みを防止) | — |
| 書き込み | 一時ファイルに書いてから差し替え。転送が途切れても壊れたファイルを残さない | — |
| 総当たり | PIN失敗が5分間に10回でそのIPを一時ブロック | — |

`_backup/` `_trash/` `.lanshare/` は共有フォルダ内に作られるが、一覧には表示されない。
不要になったらエクスプローラーで中身を確認してから削除する。

## コマンドラインオプション

```
-d, --dir DIR              共有フォルダ(既定: ./shared)
-p, --port PORT            待ち受けポート(既定: 8765)
    --host HOST            待ち受けアドレス(既定: 0.0.0.0)
    --pin PIN              PINを固定する(既定: 起動ごとに自動生成)
    --no-auth              PIN認証を無効にする
    --allow-any-client     プライベートIP以外からの接続も許可する
    --max-upload SIZE      1ファイルの上限(例: 2G、500M)
    --on-conflict {rename,backup}
    --hard-delete          削除時にゴミ箱へ退避しない(復元不可)
    --session-ttl HOURS    ログインの有効時間(既定: 12)
    --no-qr                起動時のQR表示を省略
    --open                 起動後にPCのブラウザで開く
-q, --quiet                アクセスログを表示しない
```

## Windowsファイアウォール

初回起動時に「Windows Defender ファイアウォール」のダイアログが出たら、
**「プライベート ネットワーク」にチェックを入れて「アクセスを許可する」**。
(パブリックネットワークは許可しない。)

誤って拒否した場合は、管理者権限のPowerShellで許可を追加できる。

```powershell
New-NetFirewallRule -DisplayName "LAN File Share 8765" -Direction Inbound `
  -Protocol TCP -LocalPort 8765 -Profile Private -Action Allow
```

削除するときは `Remove-NetFirewallRule -DisplayName "LAN File Share 8765"`。

## つながらないときは

| 症状 | 確認すること |
|------|------------|
| iPhoneでページが開かない | PCとiPhoneが同じWi-Fiか(iPhoneがモバイル通信になっていないか) |
| 同上 | Windowsファイアウォールで許可したか(上記) |
| 同上 | ホテル・社内・ゲスト用Wi-Fiは端末間通信が遮断(APアイソレーション)されていることが多い。テザリングやルーター直下のWi-Fiで試す |
| URLのIPが違う | PCが複数のIPを持つ場合、コンソールに出た**すべてのURL**を順に試す |
| `ポート 8765 は使用中です` | `--port 8081` など別の番号を指定する |
| PINを忘れた | サーバを再起動すると新しいPINが表示される(`--pin` で固定も可) |
| アップロードが途中で止まる | iPhoneがスリープすると転送が中断する。大きい動画は画面をつけたままにする |

## 仕組み

| ファイル | 役割 |
|---------|------|
| `__main__.py` | コマンドライン引数の解析と起動 |
| `server.py` | HTTPサーバ(スレッド並列)と起動バナー |
| `handler.py` | ルーティング、認証チェック、ダウンロード(Range対応) |
| `multipart.py` | multipart/form-dataのストリーミング解析(大きなファイルをメモリに載せない) |
| `storage.py` | 共有フォルダの読み書き、ファイル名の正規化、バックアップ・ゴミ箱 |
| `auth.py` | PIN照合、セッション、試行回数制限 |
| `clips.py` | テキスト共有の保管 |
| `qr.py` | QRコード生成(バイトモード、バージョン1〜10、PNG/AA出力) |
| `netinfo.py` | LAN内IPの取得、接続元の判定 |
| `web/` | 画面(HTML/CSS/JS。iPhone Safari向けにレイアウト調整) |

### HTTP API

| メソッド | パス | 内容 |
|---------|------|------|
| GET | `/` | 画面(`?pin=` 付きならQRからの自動ログイン) |
| GET | `/qr.png` | 接続用QRコード |
| GET | `/api/info` `/api/files` `/api/clips` | サーバ情報・ファイル一覧・共有テキスト |
| GET | `/files/<name>` | ダウンロード(`?dl=1` で保存、Rangeリクエスト対応) |
| POST | `/api/login` `/api/logout` | PIN認証 |
| POST | `/api/upload` | アップロード(multipart/form-data) |
| POST | `/api/delete` | 削除(既定はゴミ箱へ退避) |
| POST | `/api/clips` `/api/clips/delete` | テキスト共有の追加・削除 |

書き込み系のAPIは `X-LanShare` ヘッダを要求し、CookieはSameSite=Strictにしてある
(他サイトのページから勝手に操作されるのを防ぐため)。

## テスト

```bash
python -m unittest discover -s lanshare/tests -t .
```

QRコードのテストは、生成した行列を逆に読み戻して
誤り訂正符号のシンドロームが0になること・本文が一致することまで検証している。

## 制限事項

- 通信はHTTP(暗号化なし)。**同じLAN内で使う前提**で、インターネットに公開しないこと
  (ルーターのポート開放やDMZ設定は行わない)
- フォルダ階層は扱わない(共有フォルダ直下のファイルのみ)
- 動作確認はWindows + iPhone(Safari)を想定。Android/Macのブラウザでも同じURLで使える
