"""Windows向けに同梱するファイル(アイコン・起動/ショートカット用スクリプト)の検証。

Windowsでしか実行できないスクリプトのため、ここでは
* 文字化けしない形式で保存されているか(PowerShellはBOMなしUTF-8を既定コードページで読む)
* 参照しているファイル名やフォルダの決め方が壊れていないか
* アイコンがWindowsの扱えるICO構造になっているか
を確認する。
"""

import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "lanshare.ico"
PS1 = ROOT / "install-shortcut.ps1"
BATCH_FILES = [ROOT / "start-server.bat", ROOT / "install-shortcut.bat", ROOT / "remove-shortcut.bat"]


class IconTest(unittest.TestCase):
    def setUp(self):
        self.data = ICON.read_bytes()

    def test_ico_directory(self):
        reserved, kind, count = struct.unpack("<HHH", self.data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        self.assertGreaterEqual(count, 5)  # 16〜256pxを揃えておく
        sizes = []
        for index in range(count):
            entry = self.data[6 + index * 16: 22 + index * 16]
            width, height, colors, _, planes, bits, length, offset = struct.unpack("<BBBBHHII", entry)
            self.assertEqual((colors, planes, bits), (0, 1, 32))
            self.assertLessEqual(offset + length, len(self.data))
            image = self.data[offset:offset + length]
            self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
            png_width, png_height = struct.unpack(">II", image[16:24])
            self.assertEqual(png_width, png_height)
            self.assertEqual(png_width % 256, width)  # 256pxは0として記録される
            self.assertEqual(image[25], 6)  # RGBA
            sizes.append(png_width)
        self.assertIn(16, sizes)
        self.assertIn(256, sizes)

    def test_icon_matches_generator(self):
        """コミットしてあるICOが make_icon.py の出力と一致すること。"""
        import importlib.util

        spec = importlib.util.spec_from_file_location("make_icon", ROOT / "assets" / "make_icon.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.build_ico(), self.data)


class PowerShellScriptTest(unittest.TestCase):
    def setUp(self):
        self.raw = PS1.read_bytes()
        self.text = self.raw.decode("utf-8-sig")

    def test_saved_as_utf8_with_bom(self):
        """BOMがないとWindows PowerShell 5.1で日本語が化ける。"""
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", self.raw)

    def test_uses_real_desktop_folder(self):
        # OneDriveでリダイレクトされたデスクトップも拾えるAPIを使う
        self.assertIn("[Environment]::GetFolderPath('Desktop')", self.text)

    def test_creates_url_shortcut_with_detected_address(self):
        """IPアドレス入りURLの .url ショートカットを作ること。"""
        self.assertIn("'[InternetShortcut]'", self.text)
        self.assertIn('"URL=$url"', self.text)
        self.assertIn("$url = 'http://{0}:{1}/' -f $primary, $Port", self.text)
        self.assertIn("($UrlName + '.url')", self.text)

    def test_detects_lan_address(self):
        lookup = self.text[self.text.index("function Get-LanAddress"):self.text.index("function Backup-Existing")]
        # 既定ゲートウェイを持つ接続を優先し、使えない環境ではDNS経由で拾う
        self.assertIn("Get-NetIPConfiguration", lookup)
        self.assertIn("IPv4DefaultGateway", lookup)
        self.assertIn("RouteMetric", lookup)
        self.assertIn("[System.Net.Dns]::GetHostAddresses", lookup)
        # ループバックとAPIPAは候補から外す
        self.assertIn("StartsWith('127.')", lookup)
        self.assertIn("StartsWith('169.254.')", lookup)

    def test_port_default_matches_server(self):
        from lanshare.config import DEFAULT_PORT

        self.assertIn(f"[int]$Port = {DEFAULT_PORT}", self.text)
        self.assertIn("[string]$Address", self.text)

    def test_falls_back_when_no_address_found(self):
        self.assertIn("$primary = '127.0.0.1'", self.text)
        self.assertIn("$reachable = $false", self.text)
        self.assertIn("iPhoneからは開けません", self.text)

    def test_url_file_written_as_ascii(self):
        """.url はANSIとして読まれるので、非ASCIIのパスは短い名前に置き換える。"""
        self.assertIn("-Encoding ASCII", self.text)
        self.assertIn("ShortPath", self.text)

    def test_points_at_launcher_and_icon(self):
        self.assertIn("start-server.bat", self.text)
        self.assertIn("assets\\lanshare.ico", self.text)
        self.assertIn("$shortcut.WorkingDirectory = $repo", self.text.replace("  ", " "))

    def test_backs_up_before_replacing(self):
        self.assertIn("yyyyMMdd-HHmmss", self.text)
        # .lnk と .url のどちらも、作り直す前に退避する
        self.assertLess(self.text.index("Backup-Existing -Path $link"), self.text.index("CreateShortcut"))
        self.assertLess(self.text.index("Backup-Existing -Path $urlLink"),
                        self.text.index("Set-Content -LiteralPath $urlLink"))

    def test_confirms_before_deleting(self):
        remove_section = self.text[self.text.index("if ($Remove)"):self.text.index("# --- 作成 ---")]
        confirm = remove_section.index("Read-Host")
        delete = remove_section.index("Remove-Item")
        self.assertLess(confirm, delete, "削除の前に確認すること")
        self.assertIn("削除します", remove_section)
        # 2つのショートカットが対象で、消えるのはそれだけだと伝える
        self.assertIn("@($link, $urlLink)", remove_section)
        self.assertIn("共有フォルダの中身やアプリ本体は消えません", remove_section)


class BatchFileTest(unittest.TestCase):
    def test_ascii_and_crlf(self):
        """cmd.exeの既定コードページで化けないようASCIIのみにする。"""
        for path in BATCH_FILES:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                raw.decode("ascii")
                self.assertIn(b"\r\n", raw)
                self.assertTrue(raw.startswith(b"@echo off"))

    def test_shortcut_batches_call_the_script(self):
        install = (ROOT / "install-shortcut.bat").read_text()
        remove = (ROOT / "remove-shortcut.bat").read_text()
        for text in (install, remove):
            self.assertIn('-ExecutionPolicy Bypass -File "%~dp0install-shortcut.ps1"', text)
        self.assertIn("-Remove", remove)
        self.assertNotIn("-Remove", install)

    def test_start_server_runs_the_module(self):
        text = (ROOT / "start-server.bat").read_text()
        self.assertIn("-m lanshare", text)
        self.assertIn('cd /d "%~dp0.."', text)  # リポジトリ直下で実行する


if __name__ == "__main__":
    unittest.main()
