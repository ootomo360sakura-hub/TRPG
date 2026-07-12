// ============================================================
// 会員ログインゲート(Google Apps Script ウェブアプリ)
//
// 仕組み:
//   - 会員名簿はGoogleスプレッドシートで管理(setup()で自動作成)
//   - パスワードは平文保存せず、ソルト付きSHA-256ハッシュで保存
//   - ログイン成功時にワンタイムトークンを発行(CacheServiceに保存)
//   - 会員コンテンツ(member.html)はトークン検証を通った場合のみ返す
//   - ログイン失敗が続くと一時ロック(総当たり対策)
//
// 使い方は同じフォルダの README.md を参照。
// ============================================================

// セッション有効時間(時間)。CacheServiceの上限が6時間なので最大6。
const SESSION_HOURS = 6;
// ログイン失敗の許容回数と、超えたときのロック時間(秒)
const MAX_FAILS = 5;
const LOCK_SECONDS = 600;

// ---- ウェブアプリのエントリポイント ----
function doGet() {
  return HtmlService.createHtmlOutputFromFile('login')
    .setTitle('会員ページ ログイン')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL); // Googleサイト埋め込み用
}

// ============================================================
// 管理用関数(スクリプトエディタから手動で実行する)
// ============================================================

// 初回セットアップ: 会員名簿スプレッドシートを作成する(一度だけ実行)
function setup() {
  const props = PropertiesService.getScriptProperties();
  const existing = props.getProperty('SHEET_ID');
  if (existing) {
    Logger.log('セットアップ済みです。名簿: https://docs.google.com/spreadsheets/d/' + existing);
    return;
  }
  const ss = SpreadsheetApp.create('会員名簿(ログインゲート用)');
  const sheet = ss.getSheets()[0];
  sheet.setName('members');
  sheet.appendRow(['id', 'name', 'salt', 'passwordHash', 'createdAt']);
  sheet.setFrozenRows(1);
  props.setProperty('SHEET_ID', ss.getId());
  Logger.log('会員名簿を作成しました: ' + ss.getUrl());
}

// 会員を追加する。エディタで実行するときは一時的に
//   addMember('taro', 'himitsu123', '太郎')
// のように引数を書いたテスト関数を作って実行するか、下のsample_addMemberを書き換えて使う。
function addMember(id, password, name) {
  id = String(id || '').trim();
  if (!id || !password) throw new Error('idとpasswordは必須です');
  if (String(password).length < 8) throw new Error('パスワードは8文字以上にしてください');
  const sheet = getMemberSheet_();
  if (findMember_(sheet, id)) throw new Error('このIDは登録済みです: ' + id);
  const salt = Utilities.getUuid();
  sheet.appendRow([id, name || id, salt, hash_(password, salt), new Date()]);
  Logger.log('会員を登録しました: ' + id);
}

// 会員を削除する(退会処理)
function removeMember(id) {
  const sheet = getMemberSheet_();
  const values = sheet.getDataRange().getValues();
  for (let i = values.length - 1; i >= 1; i--) {
    if (String(values[i][0]) === String(id).trim()) {
      sheet.deleteRow(i + 1);
      Logger.log('会員を削除しました: ' + id);
      return;
    }
  }
  Logger.log('該当IDが見つかりません: ' + id);
}

// 登録用サンプル。引数を書き換えてエディタから実行する。
function sample_addMember() {
  addMember('member01', 'kaiin-pass-01', 'メンバー01');
}

// ============================================================
// クライアント(login.html)から呼ばれる関数
// ============================================================

// ログイン検証。成功したらセッショントークンを返す。
function login(id, password) {
  id = String(id || '').trim();
  password = String(password || '');
  const cache = CacheService.getScriptCache();

  // 総当たり対策: 同一IDでの連続失敗をロック
  const failKey = 'fail:' + id;
  const fails = Number(cache.get(failKey) || 0);
  if (fails >= MAX_FAILS) {
    return { ok: false, message: '試行回数が多すぎます。しばらく待ってからやり直してください' };
  }

  const member = findMember_(getMemberSheet_(), id);
  if (member && hash_(password, member.salt) === member.passwordHash) {
    cache.remove(failKey);
    const token = Utilities.getUuid();
    cache.put('token:' + token, id, SESSION_HOURS * 3600);
    return { ok: true, token: token, name: member.name };
  }

  cache.put(failKey, String(fails + 1), LOCK_SECONDS);
  return { ok: false, message: 'IDまたはパスワードが違います' };
}

// 会員コンテンツを返す。トークンが無効ならnull(=セッション切れ)。
function getMemberContent(token) {
  const id = CacheService.getScriptCache().get('token:' + String(token));
  if (!id) return null;
  const member = findMember_(getMemberSheet_(), id) || { id: id, name: id };
  const t = HtmlService.createTemplateFromFile('member');
  t.memberName = member.name;
  return t.evaluate().getContent();
}

// ログアウト(トークン破棄)
function logout(token) {
  CacheService.getScriptCache().remove('token:' + String(token));
}

// ============================================================
// 内部ユーティリティ
// ============================================================

function getMemberSheet_() {
  const sheetId = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (!sheetId) throw new Error('先にエディタから setup() を実行してください');
  return SpreadsheetApp.openById(sheetId).getSheetByName('members');
}

function findMember_(sheet, id) {
  const values = sheet.getDataRange().getValues();
  for (let i = 1; i < values.length; i++) {
    if (String(values[i][0]) === id) {
      return { id: values[i][0], name: values[i][1], salt: values[i][2], passwordHash: values[i][3] };
    }
  }
  return null;
}

function hash_(password, salt) {
  const bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    salt + ':' + password,
    Utilities.Charset.UTF_8
  );
  return bytes.map(function (b) { return ((b + 256) % 256).toString(16).padStart(2, '0'); }).join('');
}
