"""HTTPリクエストの処理。

ブラウザ(iPhone Safari / PCブラウザ)だけをクライアントに想定した小さなAPI。
* GET  /                     UI(未認証ならログイン画面)。``?pin=`` 付きならQRからの自動ログイン
* GET  /static/*             UIのCSS/JS
* GET  /qr.png               接続用QRコード(要認証)
* GET  /api/info             サーバ情報
* GET  /api/files            ファイル一覧
* GET  /files/<name>         ダウンロード(Rangeリクエスト対応)
* POST /api/login /logout    PIN認証
* POST /api/upload           multipartアップロード(逐次書き込み)
* POST /api/delete           削除(既定はゴミ箱へ退避)
* GET/POST /api/clips        テキスト共有
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import time
import urllib.parse
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from . import __version__, qr
from .auth import SESSION_COOKIE, AuthManager, TooManyAttempts
from .clips import ClipStore
from .config import ServerConfig
from .multipart import MultipartError, MultipartParser, parse_boundary
from .netinfo import is_local_client, lan_addresses
from .storage import Store, StorageError

WEB_DIR = Path(__file__).parent / "web"
MAX_JSON_BYTES = 64 * 1024
STREAM_CHUNK = 256 * 1024


class AppContext:
    """サーバ全体で共有する状態。"""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.store = Store(config.root, on_conflict=config.on_conflict, hard_delete=config.hard_delete)
        self.auth = AuthManager(config.pin, config.session_ttl, enabled=config.require_auth)
        self.clips = ClipStore(self.store.state_dir() / "clips.json")

    def share_urls(self) -> list[str]:
        if self.config.extra_urls:
            return list(self.config.extra_urls)
        port = self.config.port
        host = self.config.host
        if host not in ("0.0.0.0", "::", ""):
            return [f"http://{host}:{port}/"]
        return [f"http://{address}:{port}/" for address in lan_addresses()] or [
            f"http://127.0.0.1:{port}/"
        ]

    def qr_url(self, with_pin: bool) -> str:
        url = self.share_urls()[0]
        if with_pin and self.auth.enabled and self.config.pin:
            url = f"{url}?pin={self.config.pin}"
        return url


class _LimitedReader:
    """Content-Length を超えて読まないラッパ。"""

    def __init__(self, stream, limit: int):
        self._stream = stream
        self._remaining = limit

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        want = self._remaining if size is None or size < 0 else min(size, self._remaining)
        data = self._stream.read(want)
        self._remaining -= len(data)
        return data


class LanShareHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"LanShare/{__version__}"
    sys_version = ""
    context: AppContext  # サーバ生成時に注入する

    # --- ログ ---

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if self.context.config.quiet:
            return
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] {self.address_string()} {format % args}", flush=True)

    def log_error(self, format: str, *args) -> None:  # noqa: A002
        self.log_message(format, *args)

    # --- 低レベルの応答 ---

    def _send(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        merged = {"Cache-Control": "no-store", **(headers or {})}
        self._send(status, body, "application/json; charset=utf-8", merged)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    # --- リクエストの読み取り ---

    def _client(self) -> str:
        return self.client_address[0] if self.client_address else "?"

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            cookie = SimpleCookie(raw)
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _authenticated(self) -> bool:
        return self.context.auth.is_valid(self._cookie_token())

    def _session_cookie(self, token: str) -> str:
        ttl = self.context.config.session_ttl
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={ttl}"

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_JSON_BYTES:
            raise ValueError("リクエスト本文が不正です")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("リクエスト本文が不正です")
        return data

    def _guard(self) -> bool:
        """接続元の制限をチェックする。通過したらTrue。"""
        if self.context.config.allow_any_client or is_local_client(self._client()):
            return True
        self.log_message("BLOCK %s (LAN外からの接続)", self._client())
        self._error(HTTPStatus.FORBIDDEN, "LAN外からの接続は許可されていません")
        return False

    def _csrf_ok(self) -> bool:
        if self.headers.get("X-LanShare"):
            return True
        self._error(HTTPStatus.BAD_REQUEST, "不正なリクエストです")
        return False

    # --- ルーティング ---

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard():
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            return self._serve_index(query)
        if path == "/favicon.ico":
            return self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/qr.png":
            return self._serve_qr()
        if path == "/api/info":
            return self._api_info()
        if path == "/api/files":
            return self._api_files()
        if path == "/api/clips":
            return self._api_clips()
        if path.startswith("/files/"):
            return self._serve_download(path[len("/files/"):], query)
        self._error(HTTPStatus.NOT_FOUND, "見つかりません")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard():
            return
        path = urllib.parse.urlsplit(self.path).path
        if not self._csrf_ok():
            return

        if path == "/api/login":
            return self._api_login()
        if path == "/api/logout":
            return self._api_logout()

        if not self._authenticated():
            self.close_connection = True
            return self._error(HTTPStatus.UNAUTHORIZED, "認証が必要です")

        if path == "/api/upload":
            return self._api_upload()
        if path == "/api/delete":
            return self._api_delete()
        if path == "/api/clips":
            return self._api_add_clip()
        if path == "/api/clips/delete":
            return self._api_delete_clip()
        self._error(HTTPStatus.NOT_FOUND, "見つかりません")

    # --- 静的ファイル ---

    def _serve_index(self, query: dict[str, list[str]]) -> None:
        pin = (query.get("pin") or [""])[0]
        if pin and not self._authenticated():
            try:
                token = self.context.auth.login(pin, self._client())
            except (ValueError, TooManyAttempts):
                self.log_message("LOGIN失敗 (QR経由)")
            else:
                self.log_message("LOGIN成功 (QR経由)")
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", self._session_cookie(token))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self._serve_static("index.html")

    def _serve_static(self, name: str) -> None:
        safe = posixpath.normpath("/" + name).lstrip("/")
        path = (WEB_DIR / safe).resolve()
        if not str(path).startswith(str(WEB_DIR.resolve())) or not path.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "見つかりません")
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(path.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, path.read_bytes(), content_type, {"Cache-Control": "no-cache"})

    def _serve_qr(self) -> None:
        url = self.context.qr_url(with_pin=self._authenticated())
        try:
            code = qr.make(url, "M")
        except qr.QRError as error:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
        self._send(HTTPStatus.OK, code.to_png(scale=6, border=3), "image/png", {"Cache-Control": "no-store"})

    # --- API ---

    def _api_info(self) -> None:
        if not self._authenticated():
            return self._error(HTTPStatus.UNAUTHORIZED, "認証が必要です")
        config = self.context.config
        self._json({
            "auth": self.context.auth.enabled,
            "root": self.context.store.root.name,
            "rootPath": str(self.context.store.root),
            "onConflict": config.on_conflict,
            "hardDelete": config.hard_delete,
            "maxUpload": config.max_upload_bytes,
            "urls": self.context.share_urls(),
            "version": __version__,
        })

    def _api_files(self) -> None:
        if not self._authenticated():
            return self._error(HTTPStatus.UNAUTHORIZED, "認証が必要です")
        files = [info.as_dict() for info in self.context.store.list_files()]
        self._json({"files": files, "totalSize": sum(f["size"] for f in files)})

    def _api_login(self) -> None:
        try:
            payload = self._read_json()
        except ValueError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        try:
            token = self.context.auth.login(str(payload.get("pin", "")), self._client())
        except TooManyAttempts as error:
            self.log_message("LOGIN拒否 (試行回数超過)")
            return self._error(HTTPStatus.TOO_MANY_REQUESTS, str(error))
        except ValueError as error:
            self.log_message("LOGIN失敗")
            return self._error(HTTPStatus.UNAUTHORIZED, str(error))
        self.log_message("LOGIN成功")
        self._json({"ok": True}, headers={"Set-Cookie": self._session_cookie(token)})

    def _api_logout(self) -> None:
        self.context.auth.revoke(self._cookie_token())
        expired = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
        self._json({"ok": True}, headers={"Set-Cookie": expired})

    def _api_upload(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length が必要です")
        try:
            boundary = parse_boundary(self.headers.get("Content-Type", ""))
        except MultipartError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))

        reader = _LimitedReader(self.rfile, length)
        parser = MultipartParser(reader, boundary)
        saved: list[dict] = []
        try:
            for part in parser:
                if not part.is_file:
                    part.drain()
                    continue
                record = self.context.store.save(
                    part.filename or "file",
                    part.stream(),
                    max_bytes=self.context.config.max_upload_bytes,
                )
                saved.append(record)
                self.log_message("UPLOAD %s (%d bytes)", record["name"], record["size"])
        except (MultipartError, StorageError) as error:
            self.close_connection = True
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        except (ConnectionError, TimeoutError):
            self.close_connection = True
            self.log_message("UPLOAD中断(接続が切れました)")
            return
        if not saved:
            return self._error(HTTPStatus.BAD_REQUEST, "ファイルが含まれていません")
        self._json({"saved": saved})

    def _api_delete(self) -> None:
        try:
            payload = self._read_json()
            result = self.context.store.delete(str(payload.get("name", "")))
        except (ValueError, StorageError) as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        self.log_message(
            "DELETE %s -> %s", result["name"], result["trashed"] or "完全削除"
        )
        self._json({"ok": True, **result})

    def _api_clips(self) -> None:
        if not self._authenticated():
            return self._error(HTTPStatus.UNAUTHORIZED, "認証が必要です")
        self._json({"clips": self.context.clips.list()})

    def _api_add_clip(self) -> None:
        try:
            payload = self._read_json()
            clip = self.context.clips.add(str(payload.get("text", "")), source=self._client())
        except ValueError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        self.log_message("CLIP追加 (%d文字)", len(clip["text"]))
        self._json({"ok": True, "clip": clip})

    def _api_delete_clip(self) -> None:
        try:
            payload = self._read_json()
        except ValueError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        removed = self.context.clips.delete(str(payload.get("id", "")))
        if not removed:
            return self._error(HTTPStatus.NOT_FOUND, "見つかりません")
        self.log_message("CLIP削除")
        self._json({"ok": True})

    # --- ダウンロード ---

    def _serve_download(self, raw_name: str, query: dict[str, list[str]]) -> None:
        if not self._authenticated():
            return self._error(HTTPStatus.UNAUTHORIZED, "認証が必要です")
        name = raw_name.split("?")[0]
        try:
            path = self.context.store.resolve(name)
        except StorageError as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        if not path.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "見つかりません")

        size = path.stat().st_size
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        disposition = "attachment" if query.get("dl") else "inline"
        quoted = urllib.parse.quote(name)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quoted}",
            "Cache-Control": "no-store",
        }

        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            parsed_range = _parse_range(range_header, size)
            if parsed_range is None:
                return self._send(
                    HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", content_type,
                    {"Content-Range": f"bytes */{size}"},
                )
            start, end = parsed_range
            status = HTTPStatus.PARTIAL_CONTENT
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"

        length = 0 if size == 0 else end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command == "HEAD" or length == 0:
            return

        self.log_message("DOWNLOAD %s (%d bytes)", name, length)
        try:
            for chunk in self.context.store.iter_range(name, start, end, STREAM_CHUNK):
                self.wfile.write(chunk)
        except (ConnectionError, TimeoutError, OSError):
            self.close_connection = True
            self.log_message("DOWNLOAD中断 %s", name)


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """``Range: bytes=...`` を (start, end) に変換する。不正ならNone。"""
    if not header.startswith("bytes=") or "," in header:
        return None
    spec = header[len("bytes="):].strip()
    if size == 0:
        return None
    try:
        if spec.startswith("-"):
            suffix = int(spec[1:])
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            return (start, size - 1)
        start_text, _, end_text = spec.partition("-")
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return (start, min(end, size - 1))


def make_handler(context: AppContext):
    """コンテキストを束縛したハンドラクラスを返す。"""
    return type("BoundLanShareHandler", (LanShareHandler,), {"context": context})


mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("video/quicktime", ".mov")
