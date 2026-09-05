"""共有フォルダの読み書き。

フォルダ階層をそのまま保つ。フォルダごと受け取り、フォルダごとZIPで渡せる。
受け取るファイルの種類とサイズに制限は設けない(上限はPCの空き容量とファイルシステム)。
そのうえで安全側の既定として、
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
import zipfile
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


MAX_DEPTH = 24


def sanitize_relative_path(raw: str) -> str:
    """受信した相対パスを、共有フォルダ内で安全に使える形へ正規化する。

    ``[E]あさひなぐ/01巻/001.jpg`` のような階層を保ったまま、各段をWindowsで
    使える名前に直す。``..`` などの上位参照は捨てる。
    """
    segments = []
    for segment in re.split(r"[\\/]+", raw or ""):
        segment = segment.strip()
        if not segment or segment in (".", ".."):
            continue
        segments.append(sanitize_filename(segment))
    if not segments:
        return "file"
    return "/".join(segments[:MAX_DEPTH])


def timestamp(now: float | None = None) -> str:
    """バックアップ・ゴミ箱で使う ``YYYYMMDD-HHMMSS`` 形式の日時文字列。"""
    return datetime.fromtimestamp(now if now is not None else time.time()).strftime("%Y%m%d-%H%M%S")


class _StreamBuffer:
    """ZipFile の書き込み先。溜まったぶんを順に取り出して送信に回す。

    ``seek`` を持たないことで ZipFile が「巻き戻せない出力先」として扱い、
    サイズ不明のままでも正しいZIPを書き出す。
    """

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._position = 0

    def write(self, data) -> int:
        data = bytes(data)
        self._chunks.append(data)
        self._position += len(data)
        return len(data)

    def tell(self) -> int:
        return self._position

    def flush(self) -> None:
        pass

    def drain(self) -> Iterator[bytes]:
        chunks, self._chunks = self._chunks, []
        yield from chunks


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


@dataclass(frozen=True)
class FolderInfo:
    name: str
    entries: int
    mtime: float

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "entries": self.entries,
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

    def resolve(self, relative: str) -> Path:
        """共有フォルダ内のパスを安全に解決する(サブフォルダ可)。

        受け取った名前は書き換えず、共有フォルダの外を指していないか、
        退避用フォルダ(``_trash`` など)に触れていないかだけを検証する。
        """
        if not relative or relative in (".", ".."):
            raise StorageError("不正なファイル名です")
        segments = [segment for segment in re.split(r"[\\/]+", relative) if segment]
        if not segments or any(segment in (".", "..") for segment in segments):
            raise StorageError("不正なファイル名です")
        if segments[0] in RESERVED_DIRS:
            raise StorageError("このフォルダは画面からは操作できません")
        path = (self.root / Path(*segments)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            raise StorageError("共有フォルダの外は参照できません") from None
        if path == self.root:
            raise StorageError("不正なファイル名です")
        return path

    def state_dir(self) -> Path:
        path = self.root / STATE_DIR
        path.mkdir(exist_ok=True)
        return path

    # --- 一覧 ---

    def directory(self, relative: str = "") -> Path:
        """相対パスをフォルダとして解決する(空文字なら共有フォルダ自身)。"""
        if not relative:
            return self.root
        path = self.resolve(relative)
        if not path.is_dir():
            raise StorageError("フォルダが見つかりません")
        return path

    def list_dir(self, relative: str = "") -> tuple[list[FolderInfo], list[FileInfo]]:
        """指定フォルダ直下のフォルダとファイルを返す。"""
        base = self.directory(relative)
        folders: list[FolderInfo] = []
        files: list[FileInfo] = []
        for entry in os.scandir(base):
            if entry.name.startswith(".") or entry.name.endswith(".lanshare-part"):
                continue
            if not relative and entry.name in RESERVED_DIRS:
                continue
            try:
                stat = entry.stat()
                if entry.is_dir():
                    folders.append(FolderInfo(entry.name, sum(1 for _ in os.scandir(entry.path)), stat.st_mtime))
                elif entry.is_file():
                    files.append(FileInfo(entry.name, stat.st_size, stat.st_mtime))
            except OSError:
                continue  # 転送中に消えた等は無視する
        folders.sort(key=lambda info: info.name)
        files.sort(key=lambda info: info.mtime, reverse=True)
        return folders, files

    def list_files(self, relative: str = "") -> list[FileInfo]:
        return self.list_dir(relative)[1]

    def total_size(self, relative: str = "") -> int:
        return sum(info.size for info in self.list_files(relative))

    def free_space(self) -> int | None:
        """共有フォルダのあるドライブの空き容量(バイト)。取得できなければNone。"""
        try:
            return shutil.disk_usage(self.root).free
        except OSError:
            return None

    # --- 保存 ---

    def _unique_path(self, relative: str) -> str:
        """同名があるときに ``名前 (1).拡張子`` へずらした相対パスを返す。"""
        if not (self.root / relative).exists():
            return relative
        parent, _, name = relative.rpartition("/")
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        for index in range(1, 10000):
            candidate = f"{stem} ({index}).{ext}" if ext else f"{stem} ({index})"
            full = f"{parent}/{candidate}" if parent else candidate
            if not (self.root / full).exists():
                return full
        raise StorageError("同名ファイルが多すぎます")

    def backup(self, relative: str) -> Path:
        """既存ファイルを ``_backup/`` へ日時付きで退避し、退避先を返す。

        フォルダの構成はそのまま ``_backup/`` の下に再現する。
        """
        source = self.resolve(relative)
        parent, _, name = relative.replace("\\", "/").rpartition("/")
        backup_dir = self.root / BACKUP_DIR / parent if parent else self.root / BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
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

    def save(self, filename: str, chunks: Iterable[bytes]) -> dict:
        """チャンク列をファイルとして保存し、結果の情報を返す。

        ``filename`` に ``フォルダ/ファイル`` のような相対パスを渡すと、
        フォルダを作ってその中に保存する(階層はそのまま保たれる)。
        ファイルの種類とサイズに制限は設けない(実際の上限はPCの空き容量)。
        同名ファイルがある場合は ``on_conflict`` に従って別名保存またはバックアップ退避。
        書き込みは一時ファイルへ行い、完了時にリネームする(中断時に壊れた本体を残さない)。
        """
        relative = sanitize_relative_path(filename)
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        temp = destination.parent / f".{os.getpid()}-{time.time_ns()}.lanshare-part"
        written = 0
        try:
            with open(temp, "wb") as handle:
                for chunk in chunks:
                    written += len(chunk)
                    handle.write(chunk)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise

        backed_up: str | None = None
        if destination.exists():
            if self.on_conflict == "backup":
                backed_up = str(self.backup(relative).relative_to(self.root)).replace("\\", "/")
            else:
                relative = self._unique_path(relative)
                destination = self.root / relative
        temp.replace(destination)
        return {"name": relative, "size": written, "backup": backed_up}

    # --- 削除 ---

    def delete_many(self, names: Iterable[str]) -> dict:
        """複数のファイルをまとめて削除する。

        ファイルでもフォルダでも消せる(フォルダは中身ごと)。
        既定では ``_trash/日時/`` へ退避するだけで、実ファイルは残す。
        1回の呼び出しで消したものは同じ日時フォルダにまとめるので、
        あとからエクスプローラーでフォルダごと戻せる。
        削除できなかったものは ``failed`` に理由付きで返し、途中で止めない。
        """
        deleted: list[dict] = []
        failed: list[dict] = []
        trash_dir: Path | None = None

        for name in names:
            try:
                path = self.resolve(name)
                if not path.exists():
                    raise StorageError("ファイルが見つかりません")
                if self.hard_delete:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    deleted.append({"name": name, "trashed": None})
                    continue
                if trash_dir is None:
                    trash_dir = self.root / TRASH_DIR / timestamp()
                    trash_dir.mkdir(parents=True, exist_ok=True)
                # フォルダの構成を保ったまま退避する
                relative = path.relative_to(self.root)
                target = trash_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                index = 1
                while target.exists():
                    target = target.with_name(f"{index}-{relative.name}")
                    index += 1
                shutil.move(str(path), str(target))
                deleted.append({
                    "name": name,
                    "trashed": str(target.relative_to(self.root)).replace("\\", "/"),
                    "kind": "folder" if target.is_dir() else "file",
                })
            except (StorageError, OSError) as error:
                failed.append({"name": name, "error": str(error)})

        return {
            "deleted": deleted,
            "failed": failed,
            "trash_dir": str(trash_dir.relative_to(self.root)) if trash_dir else None,
        }

    def delete(self, name: str) -> dict:
        """ファイル1件を削除する。既定では ``_trash/日時/`` へ退避するだけ。"""
        result = self.delete_many([name])
        if result["failed"]:
            raise StorageError(result["failed"][0]["error"])
        return result["deleted"][0]

    # --- 読み出し ---

    def iter_zip(self, relative: str = "", chunk_size: int = 256 * 1024) -> Iterator[bytes]:
        """フォルダ(空文字なら共有フォルダ全体)をZIPにして少しずつ返す。

        メモリに溜め込まないよう、書き出されたそばから吐き出す。
        写真や動画は圧縮してもほとんど縮まないため、無圧縮(格納のみ)で速度を優先する。
        """
        base = self.directory(relative)
        prefix = base.name if relative else self.root.name
        buffer = _StreamBuffer()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path in sorted(base.rglob("*")):
                parts = path.relative_to(base).parts
                if any(part.startswith(".") for part in parts):
                    continue
                if not relative and parts and parts[0] in RESERVED_DIRS:
                    continue
                if not path.is_file():
                    continue
                arcname = "/".join((prefix, *parts))
                try:
                    with archive.open(arcname, "w") as target, open(path, "rb") as source:
                        while True:
                            chunk = source.read(chunk_size)
                            if not chunk:
                                break
                            target.write(chunk)
                            yield from buffer.drain()
                except OSError:
                    continue  # 読めないファイルは飛ばして残りを届ける
                yield from buffer.drain()
        yield from buffer.drain()

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
