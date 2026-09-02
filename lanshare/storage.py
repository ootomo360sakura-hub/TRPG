"""共有フォルダの読み書き。

安全側の既定として、
* 受信ファイル名はWindowsで使える形に正規化し、共有フォルダ外へ出られないようにする
* 同名ファイルは上書きせず別名保存(``--on-conflict backup`` なら日時付きバックアップを残す)
* 削除はいきなり消さず ``_trash/日時/`` へ退避(``--hard-delete`` 指定時のみ即削除)
を実装する。
"""

from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

TRASH_DIR = "_trash"
BACKUP_DIR = "_backup"
STATE_DIR = ".lanshare"
RESERVED_DIRS = {TRASH_DIR, BACKUP_DIR, STATE_DIR}

_WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_NAME_LENGTH = 180


class StorageError(ValueError):
    """保存・削除に失敗した場合に送出する。"""


def sanitize_filename(raw: str) -> str:
    """アップロードされたファイル名をWindowsで安全に扱える形へ正規化する。"""
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/").split("/")[-1]  # ディレクトリ部を捨てる
    name = _WINDOWS_FORBIDDEN.sub("_", name).strip()
    name = name.rstrip(". ")  # Windowsは末尾のドット・空白を扱えない
    if not name or name in (".", ".."):
        name = "file"
    stem, dot, ext = name.rpartition(".")
    if dot and stem.upper() in _WINDOWS_RESERVED:
        name = f"_{name}"
    elif not dot and name.upper() in _WINDOWS_RESERVED:
        name = f"_{name}"
    if len(name) > MAX_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 12:
            keep = MAX_NAME_LENGTH - len(ext) - 1
            name = f"{stem[:keep]}.{ext}"
        else:
            name = name[:MAX_NAME_LENGTH]
    return name


def timestamp(now: float | None = None) -> str:
    """バックアップ・ゴミ箱で使う ``YYYYMMDD-HHMMSS`` 形式の日時文字列。"""
    return datetime.fromtimestamp(now if now is not None else time.time()).strftime("%Y%m%d-%H%M%S")


@dataclass(frozen=True)
class FileInfo:
    name: str
    size: int
    mtime: float

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "mtime": self.mtime,
            "modified": datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M"),
        }


class Store:
    """共有フォルダ1つ分の操作をまとめたもの。"""

    def __init__(self, root: Path, on_conflict: str = "rename", hard_delete: bool = False):
        if on_conflict not in ("rename", "backup"):
            raise ValueError("on_conflict は 'rename' か 'backup'")
        self.root = Path(root).expanduser().resolve()
        self.on_conflict = on_conflict
        self.hard_delete = hard_delete
        self.root.mkdir(parents=True, exist_ok=True)

    # --- パス解決 ---

    def resolve(self, name: str) -> Path:
        """共有フォルダ直下のファイルパスを安全に解決する。"""
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise StorageError("不正なファイル名です")
        path = (self.root / name).resolve()
        if path.parent != self.root:
            raise StorageError("共有フォルダの外は参照できません")
        return path

    def state_dir(self) -> Path:
        path = self.root / STATE_DIR
        path.mkdir(exist_ok=True)
        return path

    # --- 一覧 ---

    def list_files(self) -> list[FileInfo]:
        items: list[FileInfo] = []
        for entry in os.scandir(self.root):
            if entry.name in RESERVED_DIRS or entry.name.startswith("."):
                continue
            if not entry.is_file() or entry.name.endswith(".lanshare-part"):
                continue
            stat = entry.stat()
            items.append(FileInfo(entry.name, stat.st_size, stat.st_mtime))
        items.sort(key=lambda info: info.mtime, reverse=True)
        return items

    def total_size(self) -> int:
        return sum(info.size for info in self.list_files())

    # --- 保存 ---

    def _unique_name(self, name: str) -> str:
        if not (self.root / name).exists():
            return name
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        for index in range(1, 10000):
            candidate = f"{stem} ({index}).{ext}" if ext else f"{stem} ({index})"
            if not (self.root / candidate).exists():
                return candidate
        raise StorageError("同名ファイルが多すぎます")

    def backup(self, name: str) -> Path:
        """既存ファイルを ``_backup/`` へ日時付きで退避し、退避先を返す。"""
        source = self.resolve(name)
        backup_dir = self.root / BACKUP_DIR
        backup_dir.mkdir(exist_ok=True)
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        stamp = timestamp()
        target = backup_dir / (f"{stem}.{stamp}.{ext}" if ext else f"{stem}.{stamp}")
        index = 1
        while target.exists():
            target = backup_dir / (f"{stem}.{stamp}-{index}.{ext}" if ext else f"{stem}.{stamp}-{index}")
            index += 1
        shutil.move(str(source), str(target))
        return target

    def save(self, filename: str, chunks: Iterable[bytes], max_bytes: int | None = None) -> dict:
        """チャンク列をファイルとして保存し、結果の情報を返す。

        同名ファイルがある場合は ``on_conflict`` に従って別名保存またはバックアップ退避。
        書き込みは一時ファイルへ行い、完了時にリネームする(中断時に壊れた本体を残さない)。
        """
        name = sanitize_filename(filename)
        temp = self.root / f".{os.getpid()}-{time.time_ns()}.lanshare-part"
        written = 0
        try:
            with open(temp, "wb") as handle:
                for chunk in chunks:
                    written += len(chunk)
                    if max_bytes is not None and written > max_bytes:
                        raise StorageError(f"ファイルが上限({max_bytes}バイト)を超えました")
                    handle.write(chunk)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise

        backed_up: str | None = None
        if (self.root / name).exists():
            if self.on_conflict == "backup":
                backed_up = str(self.backup(name).relative_to(self.root))
            else:
                name = self._unique_name(name)
        temp.replace(self.root / name)
        return {"name": name, "size": written, "backup": backed_up}

    # --- 削除 ---

    def delete(self, name: str) -> dict:
        """ファイルを削除する。既定では ``_trash/日時/`` へ退避するだけ。"""
        path = self.resolve(name)
        if not path.is_file():
            raise StorageError("ファイルが見つかりません")
        if self.hard_delete:
            path.unlink()
            return {"name": name, "trashed": None}
        trash_dir = self.root / TRASH_DIR / timestamp()
        trash_dir.mkdir(parents=True, exist_ok=True)
        target = trash_dir / name
        index = 1
        while target.exists():
            target = trash_dir / f"{index}-{name}"
            index += 1
        shutil.move(str(path), str(target))
        return {"name": name, "trashed": str(target.relative_to(self.root))}

    # --- 読み出し ---

    def iter_range(self, name: str, start: int, end: int, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
        """``start``〜``end``(両端含む)のバイト列をチャンクで返す。"""
        path = self.resolve(name)
        remaining = end - start + 1
        with open(path, "rb") as handle:
            handle.seek(start)
            while remaining > 0:
                data = handle.read(min(chunk_size, remaining))
                if not data:
                    return
                remaining -= len(data)
                yield data
