"""サーバ全体の結合テスト(実際にHTTPで叩く)。"""

import http.client
import json
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

from lanshare.config import ServerConfig
from lanshare.server import banner, create_server
from lanshare.storage import BACKUP_DIR

BOUNDARY = "----lanshareITest"


def multipart(files: list[tuple[str, bytes]]) -> bytes:
    body = b""
    for filename, data in files:
        body += (
            f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body += data + b"\r\n"
    return body + f"--{BOUNDARY}--\r\n".encode()


class ServerTestCase(unittest.TestCase):
    on_conflict = "rename"
    hard_delete = False

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.config = ServerConfig(
            root=self.root, host="127.0.0.1", port=0, pin="123456",
            on_conflict=self.on_conflict, hard_delete=self.hard_delete, quiet=True,
        )
        self.server, self.context = create_server(self.config)
        self.config.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self.address = f"127.0.0.1:{self.config.port}"
        self.cookie = None

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)
        self._temp.cleanup()

    # --- ヘルパ ---

    def request(self, method, path, body=None, headers=None, csrf=True, auth=True, cookie=None):
        conn = http.client.HTTPConnection(self.address, timeout=10)
        merged = {}
        if csrf:
            merged["X-LanShare"] = "1"
        if cookie:
            merged["Cookie"] = cookie
        elif auth and self.cookie:
            merged["Cookie"] = self.cookie
        merged.update(headers or {})
        conn.request(method, path, body=body, headers=merged)
        response = conn.getresponse()
        payload = response.read()
        result = (response.status, dict(response.getheaders()), payload)
        conn.close()
        return result

    def json_request(self, method, path, payload=None, headers=None, **kwargs):
        body = json.dumps(payload or {}).encode()
        merged = {"Content-Type": "application/json", **(headers or {})}
        status, headers, raw = self.request(method, path, body, merged, **kwargs)
        try:
            return status, headers, json.loads(raw)
        except ValueError:
            return status, headers, {}

    def login(self, pin="123456"):
        status, headers, _ = self.json_request("POST", "/api/login", {"pin": pin})
        if status == 200:
            self.cookie = headers["Set-Cookie"].split(";")[0]
        return status

    def login_device(self, user_agent):
        """別端末としてログインし、そのセッションCookieを返す。"""
        status, headers, _ = self.json_request(
            "POST", "/api/login", {"pin": "123456"},
            headers={"User-Agent": user_agent}, auth=False,
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";")[0]

    def status_as(self, cookie, user_agent):
        _, _, payload = self.json_request(
            "GET", "/api/status", headers={"User-Agent": user_agent}, cookie=cookie
        )
        return payload

    def upload_files(self, files):
        body = multipart(files)
        status, headers, raw = self.request(
            "POST", "/api/upload", body,
            {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {}


class AuthFlowTest(ServerTestCase):
    def test_index_is_public_but_api_is_not(self):
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"LAN", body)
        self.assertEqual(self.request("GET", "/api/files")[0], 401)
        self.assertEqual(self.request("GET", "/api/info")[0], 401)
        self.assertEqual(self.request("GET", "/files/x.txt")[0], 401)

    def test_login_wrong_pin(self):
        self.assertEqual(self.login("000000"), 401)

    def test_login_logout(self):
        self.assertEqual(self.login(), 200)
        status, _, info = self.json_request("GET", "/api/info")
        self.assertEqual(status, 200)
        self.assertTrue(info["auth"])
        self.assertEqual(info["root"], self.root.name)
        self.assertEqual(self.json_request("POST", "/api/logout")[0], 200)
        self.assertEqual(self.request("GET", "/api/files")[0], 401)

    def test_csrf_header_required(self):
        self.assertEqual(self.json_request("POST", "/api/login", {"pin": "123456"}, csrf=False)[0], 400)

    def test_qr_auto_login_redirects_with_cookie(self):
        status, headers, _ = self.request("GET", "/?pin=123456")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertIn("lanshare_session=", headers["Set-Cookie"])

    def test_qr_auto_login_with_wrong_pin_shows_page(self):
        status, headers, _ = self.request("GET", "/?pin=999999")
        self.assertEqual(status, 200)
        self.assertNotIn("Set-Cookie", headers)

    def test_unknown_path(self):
        self.login()
        self.assertEqual(self.request("GET", "/nope")[0], 404)


class UploadDownloadTest(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_upload_multiple_and_list(self):
        status, payload = self.upload_files([("a.txt", b"hello"), ("b.bin", b"\x00\x01\x02")])
        self.assertEqual(status, 200)
        self.assertEqual([f["name"] for f in payload["saved"]], ["a.txt", "b.bin"])
        _, _, listing = self.json_request("GET", "/api/files")
        self.assertEqual(sorted(f["name"] for f in listing["files"]), ["a.txt", "b.bin"])
        self.assertEqual(listing["totalSize"], 8)

    def test_upload_sanitizes_path_traversal(self):
        status, payload = self.upload_files([("../../evil.txt", b"x")])
        self.assertEqual(status, 200)
        self.assertEqual(payload["saved"][0]["name"], "evil.txt")
        self.assertTrue((self.root / "evil.txt").is_file())
        self.assertFalse((self.root.parent / "evil.txt").exists())

    def test_upload_unicode_name_and_large_body(self):
        data = bytes(range(256)) * 20000  # 約5MB
        status, payload = self.upload_files([("写真 1.HEIC", data)])
        self.assertEqual(status, 200)
        self.assertEqual(payload["saved"][0]["size"], len(data))
        self.assertEqual((self.root / "写真 1.HEIC").read_bytes(), data)

    def test_accepts_any_file_type(self):
        """拡張子による制限は設けない。"""
        files = [("app.exe", b"MZ\x90"), ("録画.MOV", b"\x00moov"), ("no_extension", b"x"),
                 ("書庫.zip", b"PK\x03\x04"), ("メモ.txt", "日本語".encode())]
        status, payload = self.upload_files(files)
        self.assertEqual(status, 200)
        self.assertEqual([f["name"] for f in payload["saved"]], [name for name, _ in files])

    def test_upload_has_no_size_limit(self):
        """1ファイル20MBを分割受信できる(上限を設けていないこと)。"""
        data = bytes(range(256)) * 80000  # 約20MB
        status, payload = self.upload_files([("big.bin", data)])
        self.assertEqual(status, 200)
        self.assertEqual(payload["saved"][0]["size"], len(data))
        self.assertEqual((self.root / "big.bin").stat().st_size, len(data))

    def test_info_has_no_upload_limit_field(self):
        self.assertNotIn("maxUpload", self.json_request("GET", "/api/info")[2])

    def test_files_reports_free_space(self):
        free = self.json_request("GET", "/api/files")[2]["freeSpace"]
        self.assertIsInstance(free, int)
        self.assertGreater(free, 0)

    def test_disk_full_reports_clear_error(self):
        import errno as errno_module

        def full_disk(*args, **kwargs):
            raise OSError(errno_module.ENOSPC, "No space left on device")

        original = self.context.store.save
        self.context.store.save = full_disk
        try:
            status, payload = self.upload_files([("a.txt", b"x")])
        finally:
            self.context.store.save = original
        self.assertEqual(status, 507)
        self.assertIn("空き容量", payload["error"])

    def test_upload_conflict_creates_new_name(self):
        self.upload_files([("a.txt", b"1")])
        _, payload = self.upload_files([("a.txt", b"2")])
        self.assertEqual(payload["saved"][0]["name"], "a (1).txt")

    def test_upload_without_file_part(self):
        body = f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"note\"\r\n\r\nhi\r\n--{BOUNDARY}--\r\n".encode()
        status, _, _ = self.request(
            "POST", "/api/upload", body,
            {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
        )
        self.assertEqual(status, 400)

    def test_upload_rejects_non_multipart(self):
        self.assertEqual(self.json_request("POST", "/api/upload", {"a": 1})[0], 400)

    def test_download(self):
        self.upload_files([("写真 1.HEIC", b"0123456789")])
        quoted = urllib.parse.quote("写真 1.HEIC")
        status, headers, body = self.request("GET", f"/files/{quoted}")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"0123456789")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertIn("inline", headers["Content-Disposition"])
        self.assertIn(quoted, headers["Content-Disposition"])

        status, headers, _ = self.request("GET", f"/files/{quoted}?dl=1")
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_download_range_requests(self):
        self.upload_files([("a.bin", b"0123456789")])
        status, headers, body = self.request("GET", "/files/a.bin", headers={"Range": "bytes=2-5"})
        self.assertEqual(status, 206)
        self.assertEqual(body, b"2345")
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")

        status, headers, body = self.request("GET", "/files/a.bin", headers={"Range": "bytes=-3"})
        self.assertEqual((status, body), (206, b"789"))

        status, headers, body = self.request("GET", "/files/a.bin", headers={"Range": "bytes=5-"})
        self.assertEqual((status, body), (206, b"56789"))

        status, headers, _ = self.request("GET", "/files/a.bin", headers={"Range": "bytes=99-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], "bytes */10")

    def test_head_request(self):
        self.upload_files([("a.bin", b"0123456789")])
        status, headers, body = self.request("HEAD", "/files/a.bin")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Length"], "10")
        self.assertEqual(body, b"")

    def test_download_traversal_and_missing(self):
        self.assertEqual(self.request("GET", "/files/../lanshare/qr.py")[0], 400)
        self.assertEqual(self.request("GET", "/files/nope.txt")[0], 404)

    def test_delete_moves_to_trash(self):
        self.upload_files([("a.txt", b"x")])
        status, _, payload = self.json_request("POST", "/api/delete", {"name": "a.txt"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["trashed"].startswith("_trash/"))
        self.assertTrue((self.root / payload["trashed"]).is_file())
        self.assertFalse((self.root / "a.txt").exists())

    def test_delete_rejects_traversal(self):
        self.assertEqual(self.json_request("POST", "/api/delete", {"name": "../x"})[0], 400)


class BackupPolicyTest(ServerTestCase):
    on_conflict = "backup"

    def test_existing_file_is_backed_up_before_overwrite(self):
        self.login()
        self.upload_files([("a.txt", b"old")])
        _, payload = self.upload_files([("a.txt", b"new")])
        saved = payload["saved"][0]
        self.assertEqual(saved["name"], "a.txt")
        self.assertTrue(saved["backup"].startswith(f"{BACKUP_DIR}/a."))
        self.assertEqual((self.root / "a.txt").read_bytes(), b"new")
        self.assertEqual((self.root / saved["backup"]).read_bytes(), b"old")


class HardDeleteTest(ServerTestCase):
    hard_delete = True

    def test_file_is_removed_immediately(self):
        self.login()
        self.upload_files([("a.txt", b"x")])
        _, _, payload = self.json_request("POST", "/api/delete", {"name": "a.txt"})
        self.assertIsNone(payload["trashed"])
        self.assertFalse((self.root / "a.txt").exists())
        self.assertFalse((self.root / "_trash").exists())


class ClipTest(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_add_list_delete(self):
        status, _, added = self.json_request("POST", "/api/clips", {"text": "  https://example.com  "})
        self.assertEqual(status, 200)
        self.assertEqual(added["clip"]["text"], "https://example.com")
        _, _, listing = self.json_request("GET", "/api/clips")
        self.assertEqual(len(listing["clips"]), 1)
        clip_id = listing["clips"][0]["id"]
        self.assertEqual(self.json_request("POST", "/api/clips/delete", {"id": clip_id})[0], 200)
        self.assertEqual(self.json_request("GET", "/api/clips")[2]["clips"], [])
        self.assertEqual(self.json_request("POST", "/api/clips/delete", {"id": clip_id})[0], 404)

    def test_empty_text_rejected(self):
        self.assertEqual(self.json_request("POST", "/api/clips", {"text": "   "})[0], 400)

    def test_clips_persist_in_share_folder(self):
        self.json_request("POST", "/api/clips", {"text": "memo"})
        self.assertTrue((self.root / ".lanshare" / "clips.json").is_file())


class StaticAndQrTest(ServerTestCase):
    def test_static_assets(self):
        for path, marker in (("/static/app.js", b"function"), ("/static/style.css", b"--accent")):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn(marker, body)
        self.assertEqual(self.request("GET", "/static/../handler.py")[0], 404)
        self.assertEqual(self.request("GET", "/favicon.ico")[0], 204)

    def test_qr_png(self):
        status, headers, body = self.request("GET", "/qr.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_banner_contains_url_and_pin(self):
        text = banner(self.context, show_qr=False)
        self.assertIn("123456", text)
        self.assertIn(str(self.config.port), text)


class NoAuthModeTest(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.context.auth.enabled = False

    def test_api_is_open(self):
        self.assertEqual(self.request("GET", "/api/files")[0], 200)
        self.assertEqual(self.upload_files([("a.txt", b"x")])[0], 200)


IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class DeviceStatusTest(ServerTestCase):
    """セットアップ画面 → iPhone接続 → 転送画面 の流れを支える /api/status。"""

    def test_requires_auth(self):
        self.assertEqual(self.request("GET", "/api/status")[0], 401)

    def test_pc_alone_sees_no_other_device(self):
        pc = self.login_device(WINDOWS_UA)
        status = self.status_as(pc, WINDOWS_UA)
        self.assertFalse(status["otherConnected"])
        self.assertFalse(status["mobileConnected"])
        self.assertEqual(len(status["devices"]), 1)
        self.assertTrue(status["devices"][0]["self"])
        self.assertEqual(status["devices"][0]["name"], "Windows PC")

    def test_iphone_connection_is_visible_to_pc(self):
        pc = self.login_device(WINDOWS_UA)
        self.status_as(pc, WINDOWS_UA)

        phone = self.login_device(IPHONE_UA)
        self.status_as(phone, IPHONE_UA)  # iPhone側の初回アクセスで端末が登録される

        status = self.status_as(pc, WINDOWS_UA)
        self.assertTrue(status["otherConnected"])
        self.assertTrue(status["mobileConnected"])
        self.assertEqual(status["latestDevice"], "iPhone")
        names = sorted(device["name"] for device in status["devices"])
        self.assertEqual(names, ["Windows PC", "iPhone"])

        # iPhone側から見ると、PCが「自分以外の端末」になる
        phone_status = self.status_as(phone, IPHONE_UA)
        self.assertTrue(phone_status["otherConnected"])
        self.assertFalse(phone_status["mobileConnected"])

    def test_logout_removes_device(self):
        pc = self.login_device(WINDOWS_UA)
        phone = self.login_device(IPHONE_UA)
        self.status_as(phone, IPHONE_UA)
        self.assertTrue(self.status_as(pc, WINDOWS_UA)["otherConnected"])

        self.json_request("POST", "/api/logout", cookie=phone)
        self.assertFalse(self.status_as(pc, WINDOWS_UA)["otherConnected"])

    def test_revision_changes_on_upload_and_delete(self):
        self.login()
        before = self.json_request("GET", "/api/status")[2]["revision"]
        self.upload_files([("a.txt", b"x")])
        after_upload = self.json_request("GET", "/api/status")[2]["revision"]
        self.assertGreater(after_upload, before)
        self.json_request("POST", "/api/delete", {"name": "a.txt"})
        self.assertGreater(self.json_request("GET", "/api/status")[2]["revision"], after_upload)

    def test_revision_changes_on_clip(self):
        self.login()
        before = self.json_request("GET", "/api/status")[2]["revision"]
        self.json_request("POST", "/api/clips", {"text": "memo"})
        self.assertGreater(self.json_request("GET", "/api/status")[2]["revision"], before)

    def test_info_exposes_pin_for_setup_screen(self):
        self.login()
        info = self.json_request("GET", "/api/info")[2]
        self.assertEqual(info["pin"], "123456")


if __name__ == "__main__":
    unittest.main()
