"use strict";

const $ = (id) => document.getElementById(id);
const HEADERS = { "X-LanShare": "1" };

let info = { auth: false, root: "", hardDelete: false, onConflict: "rename", urls: [], maxUpload: null };

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

function showLogin() {
  $("app").classList.add("hidden");
  $("login").classList.remove("hidden");
  $("pin").focus();
}

/* ---------- 起動 ---------- */

async function boot() {
  try {
    info = await api("/api/info");
  } catch (error) {
    return; // 未認証ならログイン画面が出ている
  }
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
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
  await Promise.all([loadFiles(), loadClips()]);
}

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
  $("file-count").textContent = data.files.length
    ? `(${data.files.length}件 / ${formatSize(data.totalSize)})`
    : "";
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

function enqueue(files) {
  for (const file of files) {
    if (info.maxUpload && file.size > info.maxUpload) {
      toast(`${file.name} は上限(${formatSize(info.maxUpload)})を超えています`);
      continue;
    }
    const item = document.createElement("li");
    item.innerHTML =
      `<div class="upload-name"></div>` +
      `<progress max="100" value="0"></progress>` +
      `<div class="upload-state">待機中</div>`;
    item.querySelector(".upload-name").textContent = `${file.name} (${formatSize(file.size)})`;
    $("uploads").append(item);
    queue.push({ file, item });
  }
  pump();
}

function pump() {
  if (uploading) return;
  const job = queue.shift();
  if (!job) {
    loadFiles().catch(() => {});
    return;
  }
  uploading = true;
  const { file, item } = job;
  const bar = item.querySelector("progress");
  const state = item.querySelector(".upload-state");
  state.textContent = "送信中…";

  const form = new FormData();
  form.append("file", file, file.name);

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
      state.textContent = saved && saved.name !== file.name ? `完了(${saved.name} として保存)` : "完了";
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
    state.textContent = "失敗: 通信エラー";
    state.classList.add("failed");
    pump();
  });
  request.send(form);
}

$("pick").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (event) => {
  enqueue(event.target.files);
  event.target.value = "";
});

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
  if (event.dataTransfer && event.dataTransfer.files.length) enqueue(event.dataTransfer.files);
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
