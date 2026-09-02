"""multipartストリーミングパーサの検証。"""

import io
import unittest

from lanshare.multipart import MultipartError, MultipartParser, Part, parse_boundary

BOUNDARY = "----lanshareTest"


def build(parts: list[tuple[str, str | None, bytes]], preamble: bool = True) -> bytes:
    body = b"preamble text\r\n" if preamble else b""
    for name, filename, data in parts:
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        body += f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n\r\n".encode()
        body += data + b"\r\n"
    return body + f"--{BOUNDARY}--\r\n".encode()


def parse(body: bytes, chunk_size: int = 64 * 1024) -> list[Part]:
    parser = MultipartParser(io.BytesIO(body), BOUNDARY.encode(), chunk_size=chunk_size)
    result = []
    for part in parser:
        payload = b"".join(part.stream())
        result.append((part.name, part.filename, payload))
    return result


class BoundaryTest(unittest.TestCase):
    def test_quoted_and_bare(self):
        self.assertEqual(parse_boundary('multipart/form-data; boundary="ab cd"'), b"ab cd")
        self.assertEqual(parse_boundary("multipart/form-data; boundary=abcd"), b"abcd")

    def test_rejects_other_types(self):
        for header in ("", "application/json", "multipart/form-data"):
            with self.assertRaises(MultipartError):
                parse_boundary(header)


class ParserTest(unittest.TestCase):
    def test_fields_and_files(self):
        body = build([("note", None, "こんにちは".encode()), ("file", "a b.txt", b"DATA")])
        self.assertEqual(
            parse(body),
            [("note", None, "こんにちは".encode()), ("file", "a b.txt", b"DATA")],
        )

    def test_boundary_like_content(self):
        payload = b"line\r\n--" + BOUNDARY.encode() + b"xx\r\nstill data"
        body = build([("file", "f.bin", payload)])
        self.assertEqual(parse(body)[0][2], payload)

    def test_small_chunks(self):
        payload = bytes(range(256)) * 40
        body = build([("file", "f.bin", payload)])
        for chunk_size in (1, 3, 17, 1024):
            with self.subTest(chunk_size=chunk_size):
                self.assertEqual(parse(body, chunk_size)[0][2], payload)

    def test_empty_file_part(self):
        self.assertEqual(parse(build([("file", "empty.txt", b"")]))[0][2], b"")

    def test_unconsumed_part_is_drained(self):
        body = build([("skip", "a.txt", b"X" * 5000), ("keep", "b.txt", b"OK")])
        parser = MultipartParser(io.BytesIO(body), BOUNDARY.encode(), chunk_size=64)
        seen = []
        for part in parser:
            if part.filename == "b.txt":
                seen.append(b"".join(part.stream()))
        self.assertEqual(seen, [b"OK"])

    def test_truncated_body(self):
        body = build([("file", "a.txt", b"12345")])[:-20]
        with self.assertRaises(MultipartError):
            parse(body)

    def test_read_text_limit(self):
        body = build([("note", None, b"x" * 100)])
        parser = MultipartParser(io.BytesIO(body), BOUNDARY.encode())
        part = next(iter(parser))
        with self.assertRaises(MultipartError):
            part.read_text(limit=10)

    def test_stream_twice_fails(self):
        parser = MultipartParser(io.BytesIO(build([("f", "a", b"1")])), BOUNDARY.encode())
        part = next(iter(parser))
        b"".join(part.stream())
        with self.assertRaises(MultipartError):
            part.stream()

    def test_no_preamble(self):
        body = build([("file", "a.txt", b"data")], preamble=False)
        self.assertEqual(parse(body)[0][2], b"data")


if __name__ == "__main__":
    unittest.main()
