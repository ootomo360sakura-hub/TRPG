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

    def test_points_at_launcher_and_icon(self):
        self.assertIn("start-server.bat", self.text)
        self.assertIn("assets\\lanshare.ico", self.text)
        self.assertIn("$shortcut.WorkingDirectory = $repo", self.text.replace("  ", " "))

    def test_backs_up_before_replacing(self):
        backup = self.text.index("Copy-Item")
        create = self.text.index("CreateShortcut")
        self.assertLess(backup, create, "既存のショートカットを退避してから作り直すこと")
        self.assertIn("yyyyMMdd-HHmmss", self.text)

    def test_confirms_before_deleting(self):
        remove_section = self.text[self.text.index("if ($Remove)"):]
        confirm = remove_section.index("Read-Host")
        delete = remove_section.index("Remove-Item")
        self.assertLess(confirm, delete, "削除の前に確認すること")
        self.assertIn("削除します", remove_section)


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
