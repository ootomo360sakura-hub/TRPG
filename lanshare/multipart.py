"""multipart/form-data のストリーミングパーサ。

``cgi.FieldStorage`` は Python 3.13 で削除され、また巨大ファイルを一度メモリや
一時ファイルへ丸ごと読み込む。iPhoneから数GBの動画を受け取ることを想定して、
ここでは境界文字列を探しながら逐次チャンクを取り出す最小実装を用意する。
"""

from __future__ import annotations

import re
from typing import Iterator

CHUNK_SIZE = 256 * 1024
MAX_HEADER_BYTES = 16 * 1024


class MultipartError(ValueError):
    """multipartの解析に失敗した場合に送出する。"""


def parse_boundary(content_type: str) -> bytes:
    """Content-Type ヘッダから boundary を取り出す。"""
    if not content_type:
        raise MultipartError("Content-Type がありません")
    main = content_type.split(";")[0].strip().lower()
    if main != "multipart/form-data":
        raise MultipartError(f"multipart/form-data ではありません: {main}")
    match = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type, re.IGNORECASE)
    if not match:
        raise MultipartError("boundary が指定されていません")
    boundary = (match.group(1) or match.group(2)).strip()
    if not boundary:
        raise MultipartError("boundary が空です")
    return boundary.encode("ascii", "replace")


def _parse_content_disposition(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in value.split(";")[1:]:
        if "=" not in item:
            continue
        key, _, raw = item.partition("=")
        raw = raw.strip()
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1].replace('\\"', '"')
        params[key.strip().lower()] = raw
    return params


class Part:
    """multipartの1パート。本文は ``stream()`` で逐次読み出す。"""

    def __init__(self, headers: dict[str, str], body: Iterator[bytes]):
        self.headers = headers
        self._body = body
        self._consumed = False
        disposition = headers.get("content-disposition", "")
        params = _parse_content_disposition(disposition)
        self.name = params.get("name")
        filename = params.get("filename")
        self.filename = filename or None

    @property
    def is_file(self) -> bool:
        return self.filename is not None

    def stream(self) -> Iterator[bytes]:
        """本文をチャンクで返す。1度しか読めない。"""
        if self._consumed:
            raise MultipartError("パートはすでに読み込み済みです")
        self._consumed = True
        return self._body

    def read_text(self, limit: int = 1 << 20, encoding: str = "utf-8") -> str:
        """本文を文字列として読む(``limit`` バイトを超えたらエラー)。"""
        buf = bytearray()
        for chunk in self.stream():
            buf += chunk
            if len(buf) > limit:
                raise MultipartError("テキストパートが大きすぎます")
        return bytes(buf).decode(encoding, "replace")

    def drain(self) -> None:
        if self._consumed:
            return
        for _ in self.stream():
            pass


class MultipartParser:
    """``multipart/form-data`` 本文を逐次解析する。"""

    def __init__(self, stream, boundary: bytes, chunk_size: int = CHUNK_SIZE):
        self._stream = stream
        self._delimiter = b"--" + boundary
        self._chunk_size = chunk_size
        self._buf = b""
        self._eof = False

    # --- 低レベル入力 ---

    def _pull(self) -> bool:
        if self._eof:
            return False
        data = self._stream.read(self._chunk_size)
        if not data:
            self._eof = True
            return False
        self._buf += data
        return True

    def _read_exact(self, count: int) -> bytes:
        while len(self._buf) < count:
            if not self._pull():
                raise MultipartError("本文が途中で終了しました")
        out, self._buf = self._buf[:count], self._buf[count:]
        return out

    def _iter_until(self, needle: bytes) -> Iterator[bytes]:
        keep = len(needle) - 1
        while True:
            index = self._buf.find(needle)
            if index >= 0:
                chunk = self._buf[:index]
                self._buf = self._buf[index + len(needle):]
                if chunk:
                    yield chunk
                return
            if len(self._buf) > keep:
                emit = self._buf[:len(self._buf) - keep]
                self._buf = self._buf[len(self._buf) - keep:]
                if emit:
                    yield emit
            if not self._pull():
                raise MultipartError("境界文字列が見つかりません(本文が途中で終了)")

    def _skip_until(self, needle: bytes) -> None:
        for _ in self._iter_until(needle):
            pass

    def _iter_body(self) -> Iterator[bytes]:
        """パート本文を境界文字列の直前まで返す。

        本文中にたまたま境界文字列と同じ並びが現れた場合(直後がCRLFでも ``--`` でも
        ない場合)は、境界ではなくデータとして扱う。
        """
        needle = b"\r\n" + self._delimiter
        keep = len(needle) - 1
        while True:
            index = self._buf.find(needle)
            if index >= 0:
                tail = index + len(needle)
                while len(self._buf) < tail + 2 and self._pull():
                    pass
                following = self._buf[tail:tail + 2]
                if following in (b"\r\n", b"--"):
                    chunk = self._buf[:index]
                    self._buf = self._buf[tail:]
                    if chunk:
                        yield chunk
                    return
                if len(following) < 2:
                    raise MultipartError("終端の境界文字列が見つかりません")
                yield self._buf[:tail]  # 偽の境界。データとして流して探索を続ける
                self._buf = self._buf[tail:]
                continue
            if len(self._buf) > keep:
                emit = self._buf[:len(self._buf) - keep]
                self._buf = self._buf[len(self._buf) - keep:]
                if emit:
                    yield emit
            if not self._pull():
                raise MultipartError("境界文字列が見つかりません(本文が途中で終了)")

    def _read_headers(self) -> dict[str, str]:
        raw = bytearray()
        for chunk in self._iter_until(b"\r\n\r\n"):
            raw += chunk
            if len(raw) > MAX_HEADER_BYTES:
                raise MultipartError("パートのヘッダが大きすぎます")
        headers: dict[str, str] = {}
        for line in bytes(raw).decode("utf-8", "replace").split("\r\n"):
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        return headers

    # --- 公開API ---

    def __iter__(self) -> Iterator[Part]:
        self._skip_until(self._delimiter)  # プリアンブルを読み飛ばす
        while True:
            marker = self._read_exact(2)
            if marker == b"--":
                return  # 終端境界
            if marker != b"\r\n":
                raise MultipartError("境界文字列の直後が不正です")
            headers = self._read_headers()
            part = Part(headers, self._iter_body())
            yield part
            part.drain()
