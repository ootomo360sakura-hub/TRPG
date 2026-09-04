"use strict";

const $ = (id) => document.getElementById(id);
const HEADERS = { "X-LanShare": "1" };

let info = { auth: false, root: "", hardDelete: false, onConflict: "rename", urls: [] };
let view = "login";        // login / setup / app
let lastRevision = null;   // 共有フォルダの更新回数(変わったら一覧を読み直す)
let pollTimer = null;

/* ---------- 共通ユーティリティ ---------- */

function toast(message, ms = 2600) {
  const el = $("toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.add("hidden"), ms);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...HEADERS, ...(options.headers || {}) },
  });
  if (response.status === 401) {
    showLogin();
    throw new Error("unauthorized");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `エラー (${response.status})`);
  return data;
}

function isMobile() {
  return /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
}

function show(name) {
  view = name;
  for (const id of ["login", "setup", "app"]) {
    $(id).classList.toggle("hidden", id !== name);
  }
}

function showLogin() {
  show("login");
  $("pin").focus();
}

function showSetup() {
  show("setup");
  $("setup-qr").src = `/qr.png?t=${Date.now()}`;
  $("setup-url").textContent = info.urls[0] || "";
  $("setup-pin").textContent = info.pin
    ? `QRが読めないときは、Safariで上のURLを開いてPIN ${info.pin} を入力`
    : "PIN認証は無効です。上のURLをSafariで開いてください";
  $("waiting").classList.remove("hidden");
  $("connected-msg").classList.add("hidden");
}

function showApp() {
  show("app");
  loadFiles().catch(() => {});
  loadClips().catch(() => {});
}

function onDeviceConnected(name) {
  if (view !== "setup") return;
  $("waiting").classList.add("hidden");
  const message = $("connected-msg");
  message.textContent = `${name || "端末"} が接続されました。ファイル転送画面へ移動します…`;
  message.classList.remove("hidden");
  setTimeout(() => {
    showApp();
    toast(`${name || "端末"} と接続中です`);
  }, 1200);
}

/* ---------- 起動 ---------- */

async function boot() {
  try {
    info = await api("/api/info");
  } catch (error) {
    return; // 未認証ならログイン画面が出ている
  }
  applyInfo();

  let status = null;
  try {
    status = await api("/api/status");
  } catch (error) {
    status = null;
  }
  lastRevision = status ? status.revision : null;
  if (status) renderDevices(status.devices);

  // PC側で、まだ他の端末がつながっていなければセットアップ(QR)画面から始める
  const skipped = sessionStorage.getItem("lanshare-skip-setup") === "1";
  if (!isMobile() && status && !status.otherConnected && !skipped) {
    showSetup();
  } else {
    showApp();
  }
  startPolling();
}

function applyInfo() {
  $("root-label").textContent = info.root;
  $("root-path").textContent = info.rootPath;
  $("policy").textContent =
    (info.onConflict === "backup"
      ? "同名ファイルは _backup/ に日時つきで退避してから上書きします。"
      : "同名ファイルは別名(連番)で保存します。") +
    (info.hardDelete
      ? " 削除は即時削除です(復元できません)。"
      : " 削除したファイルは _trash/ に日時つきで移動します。");
  $("urls").innerHTML = info.urls.map((url) => `<span>${url}</span>`).join("<br>");
  $("qr").src = `/qr.png?t=${Date.now()}`;
}

/* ---------- 接続状態の監視 ---------- */

function startPolling() {
  clearTimeout(pollTimer);
  const tick = async () => {
    try {
      const status = await api("/api/status");
      renderDevices(status.devices);
      if (view === "setup" && status.otherConnected) {
        onDeviceConnected(status.latestDevice);
      }
      if (view === "app" && lastRevision !== null && status.revision !== lastRevision) {
        loadFiles().catch(() => {});
        loadClips().catch(() => {});
      }
      lastRevision = status.revision;
    } catch (error) {
      // 未認証・一時的な通信エラーは次回の巡回で回復させる
    }
    pollTimer = setTimeout(tick, document.hidden ? 10000 : 2000);
  };
  tick();
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && view !== "login") startPolling();
});

function renderDevices(devices) {
  const list = $("devices");
  if (!list) return;
  list.innerHTML = "";
  for (const device of devices || []) {
    const item = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = `dot${device.online ? " online" : ""}`;
    const name = document.createElement("span");
    name.className = "device-name";
    name.textContent = device.name + (device.self ? "(この端末)" : "");
    const meta = document.createElement("span");
    meta.className = "device-meta";
    meta.textContent = `${device.address} ・ ${device.online ? "接続中" : "切断"}`;
    item.append(dot, name, meta);
    list.append(item);
  }
  if (!(devices || []).length) {
    const item = document.createElement("li");
    item.className = "muted";
    item.textContent = "接続中の端末はありません";
    list.append(item);
  }
}

$("skip-setup").addEventListener("click", () => {
  sessionStorage.setItem("lanshare-skip-setup", "1");
  showApp();
});

$("show-setup").addEventListener("click", () => {
  sessionStorage.removeItem("lanshare-skip-setup");
  showSetup();
});

/* ---------- ログイン ---------- */

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const pin = $("pin").value.trim();
  $("login-error").textContent = "";
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { ...HEADERS, "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "接続できませんでした");
    $("pin").value = "";
    await boot();
  } catch (error) {
    $("login-error").textContent = error.message;
  }
});

$("logout").addEventListener("click", async () => {
  clearTimeout(pollTimer);
  sessionStorage.removeItem("lanshare-skip-setup");
  await fetch("/api/logout", { method: "POST", headers: HEADERS });
  location.reload();
});

/* ---------- タブ ---------- */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.id !== `tab-${tab.dataset.tab}`);
    });
  });
});

/* ---------- ファイル一覧 ---------- */

async function loadFiles() {
  const data = await api("/api/files");
  const list = $("files");
  list.innerHTML = "";
  const free = data.freeSpace ? `空き ${formatSize(data.freeSpace)}` : "";
  $("file-count").textContent = data.files.length
    ? `(${data.files.length}件 / ${formatSize(data.totalSize)}${free ? " ・ " + free : ""})`
    : free && `(${free})`;
  $("files-empty").classList.toggle("hidden", data.files.length > 0);

  for (const file of data.files) {
    const item = document.createElement("li");
    const row = document.createElement("div");
    row.className = "file-row";

    const main = document.createElement("div");
    main.className = "file-main";
    const link = document.createElement("a");
    link.className = "file-name";
    link.href = `/files/${encodeURIComponent(file.name)}`;
    link.textContent = file.name;
    const meta = document.createElement("div");
    meta.className = "file-meta";
    meta.textContent = `${formatSize(file.size)} ・ ${file.modified}`;
    main.append(link, meta);

    const actions = document.createElement("div");
    actions.className = "file-actions";
    const save = document.createElement("button");
    save.className = "link";
    save.type = "button";
    save.textContent = "保存";
    save.addEventListener("click", () => {
      location.href = `/files/${encodeURIComponent(file.name)}?dl=1`;
    });
    const remove = document.createElement("button");
    remove.className = "link danger";
    remove.type = "button";
    remove.textContent = "削除";
    remove.addEventListener("click", () => deleteFile(file));
    actions.append(save, remove);

    row.append(main, actions);
    item.append(row);
    list.append(item);
  }
}

async function deleteFile(file) {
  const detail = info.hardDelete
    ? "この操作でPC内のファイルを完全に削除します。元に戻せません。"
    : "この操作でPC内の共有フォルダからファイルを削除します(_trash/ へ日時つきで移動するので、PC側で復元できます)。";
  if (!confirm(`「${file.name}」を削除しますか?\n\n${detail}`)) return;
  try {
    const result = await api("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: file.name }),
    });
    toast(result.trashed ? `削除しました(${result.trashed} に退避)` : "完全に削除しました");
    await loadFiles();
  } catch (error) {
    toast(error.message);
  }
}

$("refresh").addEventListener("click", () => loadFiles().catch((e) => toast(e.message)));

/* ---------- アップロード ---------- */

const queue = [];
let uploading = false;

/** フォルダ内のファイルは「フォルダ名_ファイル名」で保存する(共有フォルダは階層を持たない)。 */
function flattenPath(path) {
  return path.replace(/[\\/]+/g, "_").replace(/^_+/, "");
}

/** ドロップされた項目を、フォルダの中身まで展開して {file, path} の配列にする。 */
function walkEntry(entry, prefix, found) {
  return new Promise((resolve) => {
    if (!entry) return resolve();
    if (entry.isFile) {
      entry.file(
        (file) => {
          found.push({ file, path: prefix + file.name });
          resolve();
        },
        () => {
          found.push({ path: prefix + entry.name, error: "読み取れませんでした" });
          resolve();
        }
      );
      return;
    }
    if (!entry.isDirectory) return resolve();
    const reader = entry.createReader();
    const readBatch = () => {
      reader.readEntries(
        async (batch) => {
          if (!batch.length) return resolve();
          for (const child of batch) {
            await walkEntry(child, `${prefix}${entry.name}/`, found);
          }
          readBatch(); // readEntries は一度に全件返さないので、空になるまで繰り返す
        },
        () => resolve()
      );
    };
    readBatch();
  });
}

async function collectDropped(dataTransfer) {
  // webkitGetAsEntry は drop イベント中に同期的に呼ぶ必要がある
  const entries = Array.from(dataTransfer.items || [])
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter(Boolean);
  if (!entries.length) {
    return Array.from(dataTransfer.files || []).map((file) => ({ file, path: file.name }));
  }
  const found = [];
  for (const entry of entries) {
    await walkEntry(entry, "", found);
  }
  return found;
}

function enqueue(entries) {
  let added = 0;
  for (const entry of entries) {
    const item = document.createElement("li");
    item.innerHTML =
      `<div class="upload-name"></div>` +
      `<progress max="100" value="0"></progress>` +
      `<div class="upload-state">待機中</div>`;
    const label = item.querySelector(".upload-name");
    const state = item.querySelector(".upload-state");
    if (entry.error || !entry.file) {
      label.textContent = entry.path;
      state.textContent = `失敗: ${entry.error || "読み取れませんでした"}`;
      state.classList.add("failed");
      item.querySelector("progress").remove();
      $("uploads").append(item);
      continue;
    }
    label.textContent = `${entry.path} (${formatSize(entry.file.size)})`;
    $("uploads").append(item);
    queue.push({ file: entry.file, name: flattenPath(entry.path), item });
    added += 1;
  }
  if (added > 1) toast(`${added}件を順番に送信します`);
  pump();
}

/** 送信前に先頭1バイトを読み、フォルダやクラウド上だけのファイルを見分ける。 */
async function checkReadable(file) {
  try {
    await file.slice(0, 1).arrayBuffer();
    return null;
  } catch (error) {
    if (file.size === 0 && !file.type) {
      return "フォルダはこの方法では送れません。「フォルダを選ぶ」から選ぶか、フォルダを画面にドラッグ&ドロップしてください";
    }
    return "ファイルを読み取れませんでした(OneDrive等でクラウドにのみある、または移動・削除された可能性があります)";
  }
}

async function pump() {
  if (uploading) return;
  const job = queue.shift();
  if (!job) {
    loadFiles().catch(() => {});
    return;
  }
  uploading = true;
  const { file, name, item } = job;
  const bar = item.querySelector("progress");
  const state = item.querySelector(".upload-state");
  state.textContent = "確認中…";

  const problem = await checkReadable(file);
  if (problem) {
    uploading = false;
    state.textContent = `失敗: ${problem}`;
    state.classList.add("failed");
    bar.remove();
    pump();
    return;
  }
  state.textContent = "送信中…";

  const form = new FormData();
  form.append("file", file, name);

  const request = new XMLHttpRequest();
  request.open("POST", "/api/upload");
  request.setRequestHeader("X-LanShare", "1");
  request.upload.addEventListener("progress", (event) => {
    if (event.lengthComputable) bar.value = (event.loaded / event.total) * 100;
  });
  request.addEventListener("load", () => {
    uploading = false;
    let payload = {};
    try {
      payload = JSON.parse(request.responseText);
    } catch (error) {
      payload = {};
    }
    if (request.status >= 200 && request.status < 300) {
      const saved = (payload.saved || [])[0];
      bar.value = 100;
      state.textContent = saved && saved.name !== name ? `完了(${saved.name} として保存)` : "完了";
      if (saved && saved.backup) state.textContent += ` / 既存ファイルは ${saved.backup} に退避`;
      setTimeout(() => item.remove(), 4000);
    } else {
      state.textContent = `失敗: ${payload.error || request.status}`;
      state.classList.add("failed");
      if (request.status === 401) showLogin();
    }
    pump();
  });
  request.addEventListener("error", () => {
    uploading = false;
    state.textContent = "失敗: 送信が中断されました(ファイルを読み取れないか、接続が切れました)";
    state.classList.add("failed");
    pump();
  });
  request.send(form);
}

function fromInput(input) {
  return Array.from(input.files).map((file) => ({
    file,
    path: file.webkitRelativePath || file.name,
  }));
}

$("pick").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (event) => {
  enqueue(fromInput(event.target));
  event.target.value = "";
});

if (isMobile()) {
  $("pick-folder").remove(); // iOSのSafariはフォルダ選択に対応していない
} else {
  $("pick-folder").addEventListener("click", () => $("folder-input").click());
  $("folder-input").addEventListener("change", (event) => {
    enqueue(fromInput(event.target));
    event.target.value = "";
  });
}

const drop = $("drop");
["dragenter", "dragover"].forEach((type) =>
  drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.add("over");
  })
);
["dragleave", "drop"].forEach((type) =>
  drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.remove("over");
  })
);
drop.addEventListener("drop", (event) => {
  if (!event.dataTransfer) return;
  collectDropped(event.dataTransfer)
    .then((entries) => {
      if (entries.length) enqueue(entries);
    })
    .catch(() => toast("ドロップされた内容を読み取れませんでした"));
});
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

/* ---------- テキスト共有 ---------- */

async function loadClips() {
  const data = await api("/api/clips");
  const list = $("clips");
  list.innerHTML = "";
  $("clips-empty").classList.toggle("hidden", data.clips.length > 0);
  for (const clip of data.clips) {
    const item = document.createElement("li");
    const text = document.createElement("p");
    text.className = "clip-text";
    text.textContent = clip.text;
    const meta = document.createElement("div");
    meta.className = "clip-meta";
    const when = document.createElement("span");
    when.className = "muted small";
    when.textContent = `${new Date(clip.ts * 1000).toLocaleString()} ・ ${clip.source || ""}`;
    const actions = document.createElement("span");
    const copy = document.createElement("button");
    copy.className = "link";
    copy.type = "button";
    copy.textContent = "コピー";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(clip.text);
        toast("コピーしました");
      } catch (error) {
        toast("コピーできませんでした(手動で選択してください)");
      }
    });
    const remove = document.createElement("button");
    remove.className = "link danger";
    remove.type = "button";
    remove.textContent = "削除";
    remove.addEventListener("click", async () => {
      if (!confirm("この共有テキストを削除します。よろしいですか?")) return;
      await api("/api/clips/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: clip.id }),
      });
      loadClips();
    });
    actions.append(copy, remove);
    meta.append(when, actions);
    item.append(text, meta);
    list.append(item);
  }
}

$("clip-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("clip-text").value;
  if (!text.trim()) return;
  try {
    await api("/api/clips", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    $("clip-text").value = "";
    toast("共有しました");
    loadClips();
  } catch (error) {
    toast(error.message);
  }
});

boot();
