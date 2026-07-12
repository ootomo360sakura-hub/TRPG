# Googleサイトで会員用ページを作る方法

TRPGサークルのメンバー専用ページ(セッション予定・キャラシ置き場・完成漫画の限定公開など)を
Googleサイトで運用するための手順書。

## まず知っておくこと(重要)

**Googleサイトには「独自のID・パスワードを発行してログインさせる」機能はない。**
Googleサイトのアクセス制御は **Googleアカウント単位** でしか行えない。

そのため、実現方法は次の3パターンに分かれる。

| 方法 | 安全性 | 会員側の手間 | 向いているケース |
|------|--------|--------------|------------------|
| 1. Googleアカウントで閲覧制限(公式機能) | ◎ 本物のアクセス制御 | Googleアカウントが必要 | **推奨。** 少人数の固定メンバー |
| 2. Apps Scriptで擬似パスワードゲート | △ 簡易的(URLが漏れたら見える) | 共通パスワードを入力するだけ | Googleアカウントを持たない人がいる、緩い限定公開でよい |
| 3. 外部サービスで本格認証 | ◎ | サービスによる | 独自ID/パスワードが必須要件のとき |

---

## 方法1(推奨): Googleアカウントによる閲覧制限

Google公式のアクセス制御。指定したGoogleアカウントでログインした人しかサイトを開けない。

### 手順

1. [sites.google.com](https://sites.google.com) で会員用サイトを作成する
   (公開ページと分けたい場合は、公開用と会員用で**サイト自体を2つ**作る。
   Googleサイトは「ページ単位」での閲覧制限ができないため)
2. 右上の **「共有」アイコン(人型+)** をクリック
3. 「サイトの共有」画面の **「公開アイテム」** の項目で
   **「公開」→「制限付き」** に変更する
4. 同じ画面の「ユーザーやグループを追加」に、会員の **Gmailアドレス** を入力し、
   権限を **「公開アイテムの閲覧者」** にして招待する
   (「編集者」にするとサイトを書き換えられてしまうので注意)
5. 右上の **「公開」** ボタンからサイトを公開する
6. 会員は自分のGoogleアカウントでログインした状態でサイトURLを開く。
   権限のない人が開くと「アクセス権が必要です」画面になる

### メンバーが多い場合: Googleグループで一括管理

会員の出入りのたびに共有設定をいじるのは面倒なので、
[groups.google.com](https://groups.google.com) でグループ(例: `trpg-members@googlegroups.com`)を作り、
そのグループアドレスを手順4で閲覧者に追加しておく。
以後はグループへのメンバー追加・削除だけでサイトの閲覧権限が連動する。

### メリット / デメリット

- ○ Google公式の認証なので本当に安全(URLが漏れても部外者は見られない)
- ○ 無料。追加のツール不要
- ○ 埋め込んだGoogleドライブのファイルにも同じ権限管理を適用できる
- × 会員全員にGoogleアカウントが必要
- × 「サークル共通のID/パスワード」のような運用はできない

---

## 方法2: Apps Scriptで擬似パスワードゲートを作る

「共通パスワードを入力したら会員ページに入れる」という見た目を、
Google Apps Script(GAS)のウェブアプリで実現する方法。

### 仕組み

```
公開サイトの「会員入口」ページ
  └─ GASウェブアプリを埋め込み(パスワード入力フォーム)
       └─ 正解 → 会員用コンテンツ(または隠しURL)を表示
```

### 手順

1. [script.google.com](https://script.google.com) で新規プロジェクトを作成
2. `コード.gs` に以下を貼り付ける:

```javascript
// 共通パスワードと、正解時に案内する会員ページURL
const PASSWORD = 'ここにパスワード';
const MEMBER_URL = 'https://sites.google.com/view/あなたのサイト/members';

function doGet() {
  return HtmlService.createHtmlOutputFromFile('login')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL); // サイト埋め込み許可
}

function checkPassword(input) {
  if (input === PASSWORD) {
    return MEMBER_URL;
  }
  return null;
}
```

3. 「ファイル追加 → HTML」で `login.html` を作成し、以下を貼り付ける:

```html
<!DOCTYPE html>
<html>
  <body style="font-family: sans-serif; text-align: center; padding-top: 2em;">
    <h3>会員ページ入口</h3>
    <input type="password" id="pw" placeholder="パスワード">
    <button onclick="submitPw()">入室</button>
    <p id="msg" style="color: red;"></p>
    <script>
      function submitPw() {
        google.script.run
          .withSuccessHandler(function(url) {
            if (url) {
              window.top.location.href = url; // 会員ページへ移動
            } else {
              document.getElementById('msg').textContent = 'パスワードが違います';
            }
          })
          .checkPassword(document.getElementById('pw').value);
      }
    </script>
  </body>
</html>
```

4. 右上 **「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」** を選び、
   - 「次のユーザーとして実行」: **自分**
   - 「アクセスできるユーザー」: **全員**
   でデプロイし、発行されたURLをコピーする
5. Googleサイトの入口ページで **「挿入」→「埋め込む」** にそのURLを貼り付ける
6. 会員ページ側(`MEMBER_URL` の飛び先)は「リンクを知っている全員が閲覧可」にし、
   サイトのナビゲーションから**非表示**にしておく
   (ページ設定 → 「ナビゲーションに表示」をオフ)

### 注意点(必読)

- これは**簡易ゲート**であり、本物の認証ではない。
  会員ページのURL自体が漏れると、パスワードなしで直接開けてしまう
- パスワードは全員共通なので、退会者が出たらパスワード変更+URL変更が必要
- 個人情報や課金コンテンツなど、漏れて困るものには使わないこと
- 会員ごとに別IDを発行したい場合、GASでユーザー管理を自作することは一応可能だが、
  セキュリティ的に自作認証は推奨しない → 方法3へ

---

## 方法3: 独自ID/パスワードが必須なら外部サービスを使う

「会員ごとにIDとパスワードを発行し、安全にログインさせる」ことが要件なら、
Googleサイトの守備範囲外。以下のような構成にする。

- **Firebase Hosting + Firebase Authentication**(無料枠あり):
  メール/パスワード認証を数十行のコードで実装できる。静的サイトに認証を付ける定番
- **WordPress + メンバーシッププラグイン**(例: Simple Membership):
  ノーコードに近い運用で会員制サイトを作れる
- **Cloudflare Access / Netlify のパスワード保護**:
  静的サイトの前段に認証を挟む

この場合、Googleサイトは公開用(サークル紹介・募集ページ)として使い、
会員機能は外部サイトへリンクする、という役割分担が現実的。

---

## このプロジェクトでの推奨構成

TRPGサークルの固定メンバー向けなら **方法1 + Googleグループ** が最も簡単で安全。

```
公開サイト(サークル紹介・公開漫画)      ← 誰でも閲覧可
会員サイト(セッション予定・限定漫画など) ← 「制限付き」+ Googleグループで閲覧者管理
```

完成した漫画ページ(`episodes/epNNN/page_N.png`)を限定公開したい場合は、
会員サイトに直接アップロードするか、Googleドライブの限定共有フォルダに置いて
サイトに埋め込めば、ドライブ側の権限も同じグループで揃えられる。
