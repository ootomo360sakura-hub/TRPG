"""共有フォルダ操作の検証。"""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from lanshare.storage import (
    BACKUP_DIR,
    TRASH_DIR,
    Store,
    StorageError,
    sanitize_filename,
    sanitize_relative_path,
)


class SanitizeTest(unittest.TestCase):
    def test_strips_directories(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename(r"C:\Users\me\写真.HEIC"), "写真.HEIC")
        self.assertEqual(sanitize_filename("a/b/c.txt"), "c.txt")

    def test_windows_forbidden_characters(self):
        self.assertEqual(sanitize_filename('a<b>c:d"e|f?g*h.txt'), "a_b_c_d_e_f_g_h.txt")
        self.assertEqual(sanitize_filename("bell\x07.txt"), "bell_.txt")

    def test_windows_reserved_names(self):
        self.assertEqual(sanitize_filename("con.txt"), "_con.txt")
        self.assertEqual(sanitize_filename("NUL"), "_NUL")

    def test_trailing_dots_and_spaces(self):
        self.assertEqual(sanitize_filename("report.  "), "report")
        self.assertEqual(sanitize_filename("  ..  "), "file")
        self.assertEqual(sanitize_filename(""), "file")

    def test_length_limit_keeps_extension(self):
        name = sanitize_filename("x" * 300 + ".jpg")
        self.assertLessEqual(len(name), 180)
        self.assertTrue(name.endswith(".jpg"))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_save_and_list(self):
        store = Store(self.root)
        result = store.save("メモ.txt", [b"abc", b"de"])
        self.assertEqual(result, {"name": "メモ.txt", "size": 5, "backup": None})
        self.assertEqual((self.root / "メモ.txt").read_bytes(), b"abcde")
        self.assertEqual([f.name for f in store.list_files()], ["メモ.txt"])

    def test_conflict_rename(self):
        store = Store(self.root, on_conflict="rename")
        store.save("a.txt", [b"1"])
        second = store.save("a.txt", [b"2"])
        self.assertEqual(second["name"], "a (1).txt")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"1")

    def test_conflict_backup_keeps_previous_version(self):
        store = Store(self.root, on_conflict="backup")
        store.save("a.txt", [b"old"])
        result = store.save("a.txt", [b"new"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"new")
        backups = list((self.root / BACKUP_DIR).iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"old")
        self.assertEqual(result["backup"], f"{BACKUP_DIR}/{backups[0].name}")

    def test_delete_moves_to_trash(self):
        store = Store(self.root)
        store.save("a.txt", [b"x"])
        result = store.delete("a.txt")
        self.assertFalse((self.root / "a.txt").exists())
        trashed = self.root / result["trashed"]
        self.assertTrue(trashed.is_file())
        self.assertTrue(str(trashed).startswith(str(self.root / TRASH_DIR)))

    def test_hard_delete(self):
        store = Store(self.root, hard_delete=True)
        store.save("a.txt", [b"x"])
        self.assertIsNone(store.delete("a.txt")["trashed"])
        self.assertFalse((self.root / TRASH_DIR).exists())

    def test_delete_many_groups_into_one_trash_folder(self):
        store = Store(self.root)
        for name in ("a.txt", "b.txt", "c.txt"):
            store.save(name, [b"x"])
        result = store.delete_many(["a.txt", "b.txt", "c.txt"])

        self.assertEqual([entry["name"] for entry in result["deleted"]], ["a.txt", "b.txt", "c.txt"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(list(store.list_files()), [])
        trash = self.root / result["trash_dir"]
        self.assertTrue(trash.is_dir())
        self.assertEqual(sorted(p.name for p in trash.iterdir()), ["a.txt", "b.txt", "c.txt"])
        # 退避先は1つの日時フォルダにまとまる
        self.assertEqual(len(list((self.root / TRASH_DIR).iterdir())), 1)

    def test_delete_many_continues_after_failure(self):
        store = Store(self.root)
        store.save("keep.txt", [b"x"])
        store.save("gone.txt", [b"x"])
        result = store.delete_many(["gone.txt", "missing.txt", "../etc/passwd", "keep.txt"])

        self.assertEqual([entry["name"] for entry in result["deleted"]], ["gone.txt", "keep.txt"])
        self.assertEqual([entry["name"] for entry in result["failed"]], ["missing.txt", "../etc/passwd"])
        self.assertTrue(all(entry["error"] for entry in result["failed"]))
        self.assertEqual(list(store.list_files()), [])

    def test_delete_many_hard_delete(self):
        store = Store(self.root, hard_delete=True)
        store.save("a.txt", [b"x"])
        store.save("b.txt", [b"x"])
        result = store.delete_many(["a.txt", "b.txt"])
        self.assertIsNone(result["trash_dir"])
        self.assertTrue(all(entry["trashed"] is None for entry in result["deleted"]))
        self.assertFalse((self.root / TRASH_DIR).exists())

    def test_delete_many_empty(self):
        result = Store(self.root).delete_many([])
        self.assertEqual(result, {"deleted": [], "failed": [], "trash_dir": None})

    def test_delete_missing(self):
        with self.assertRaises(StorageError):
            Store(self.root).delete("nope.txt")

    def test_resolve_rejects_traversal(self):
        store = Store(self.root)
        for name in ("../x", "a/../../x", "", ".", "..", "_trash/x", "_backup/x", ".lanshare/clips.json"):
            with self.subTest(name=name), self.assertRaises(StorageError):
                store.resolve(name)

    def test_resolve_accepts_subfolders(self):
        store = Store(self.root)
        self.assertEqual(store.resolve("a/b.txt"), self.root / "a" / "b.txt")
        self.assertEqual(store.resolve(r"a\b.txt"), self.root / "a" / "b.txt")
        self.assertEqual(store.resolve("a//b/c.txt"), self.root / "a" / "b" / "c.txt")

    def test_no_size_or_type_limit(self):
        """種類・サイズの上限は設けない(拡張子で弾かない・大きくても保存する)。"""
        store = Store(self.root)
        for name in ("script.exe", "movie.MOV", "no_extension", "書庫.zip", "写真.HEIC"):
            with self.subTest(name=name):
                self.assertEqual(store.save(name, [b"x"])["name"], name)
        chunks = (b"\xff" * 1024 * 1024 for _ in range(24))  # 24MBを逐次書き込み
        self.assertEqual(store.save("large.bin", chunks)["size"], 24 * 1024 * 1024)

    def test_write_failure_cleans_up_temp_file(self):
        store = Store(self.root)

        def failing_chunks():
            yield b"partial"
            raise OSError("disk full")

        with self.assertRaises(OSError):
            store.save("big.bin", failing_chunks())
        self.assertEqual(list(store.list_files()), [])
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".lanshare-part")], [])

    def test_free_space(self):
        free = Store(self.root).free_space()
        self.assertIsInstance(free, int)
        self.assertGreater(free, 0)

    def test_listing_hides_internal_entries(self):
        store = Store(self.root)
        store.save("a.txt", [b"x"])
        store.save("b.txt", [b"y"])
        store.delete("b.txt")
        store.state_dir()
        names = [f.name for f in store.list_files()]
        self.assertEqual(names, ["a.txt"])

    def test_iter_range(self):
        store = Store(self.root)
        store.save("a.bin", [bytes(range(10))])
        self.assertEqual(b"".join(store.iter_range("a.bin", 2, 5)), bytes(range(2, 6)))
        self.assertEqual(b"".join(store.iter_range("a.bin", 0, 9, chunk_size=3)), bytes(range(10)))

    def test_sanitizes_on_save(self):
        store = Store(self.root)
        result = store.save("../../evil.txt", [b"x"])
        self.assertEqual(result["name"], "evil.txt")
        self.assertTrue((self.root / "evil.txt").is_file())


class RelativePathTest(unittest.TestCase):
    def test_keeps_hierarchy(self):
        self.assertEqual(sanitize_relative_path("[E]あさひなぐ/01巻/001.jpg"), "[E]あさひなぐ/01巻/001.jpg")
        self.assertEqual(sanitize_relative_path(r"写真\2026\旅行.jpg"), "写真/2026/旅行.jpg")

    def test_drops_parent_references(self):
        self.assertEqual(sanitize_relative_path("../../etc/passwd"), "etc/passwd")
        self.assertEqual(sanitize_relative_path("a/./b/../c.txt"), "a/b/c.txt")
        self.assertEqual(sanitize_relative_path("///"), "file")

    def test_sanitizes_each_segment(self):
        self.assertEqual(sanitize_relative_path('a<b>/c:d.txt'), "a_b_/c_d.txt".replace("_/", "_/"))
        self.assertEqual(sanitize_relative_path("con/nul.txt"), "_con/_nul.txt")

    def test_depth_is_capped(self):
        deep = "/".join(f"d{i}" for i in range(40)) + "/x.txt"
        self.assertLessEqual(len(sanitize_relative_path(deep).split("/")), 24)


class FolderStoreTest(unittest.TestCase):
    """フォルダ階層を保った保存・一覧・ZIP・削除。"""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.store = Store(self.root)
        self.store.save("[E]あさひなぐ/01巻/001.jpg", [b"page1"])
        self.store.save("[E]あさひなぐ/01巻/002.jpg", [b"page2"])
        self.store.save("[E]あさひなぐ/表紙.jpg", [b"cover"])
        self.store.save("メモ.txt", [b"memo"])

    def tearDown(self):
        self._temp.cleanup()

    def test_saves_into_folders(self):
        self.assertEqual((self.root / "[E]あさひなぐ" / "01巻" / "001.jpg").read_bytes(), b"page1")

    def test_list_dir_separates_folders_and_files(self):
        folders, files = self.store.list_dir()
        self.assertEqual([f.name for f in folders], ["[E]あさひなぐ"])
        self.assertEqual([f.name for f in files], ["メモ.txt"])
        self.assertEqual(folders[0].entries, 2)  # 01巻 と 表紙.jpg

        folders, files = self.store.list_dir("[E]あさひなぐ")
        self.assertEqual([f.name for f in folders], ["01巻"])
        self.assertEqual([f.name for f in files], ["表紙.jpg"])

    def test_list_dir_hides_internal_folders(self):
        self.store.delete_many(["メモ.txt"])          # _trash を作る
        self.store.state_dir()                        # .lanshare を作る
        names = [f.name for f in self.store.list_dir()[0]]
        self.assertEqual(names, ["[E]あさひなぐ"])

    def test_missing_folder(self):
        with self.assertRaises(StorageError):
            self.store.list_dir("ない folder")

    def test_conflict_inside_a_folder(self):
        result = self.store.save("[E]あさひなぐ/表紙.jpg", [b"new"])
        self.assertEqual(result["name"], "[E]あさひなぐ/表紙 (1).jpg")
        self.assertEqual((self.root / "[E]あさひなぐ" / "表紙.jpg").read_bytes(), b"cover")

    def test_backup_keeps_the_folder_structure(self):
        store = Store(self.root, on_conflict="backup")
        result = store.save("[E]あさひなぐ/表紙.jpg", [b"new"])
        self.assertTrue(result["backup"].startswith(f"{BACKUP_DIR}/[E]あさひなぐ/表紙."))
        self.assertEqual((self.root / result["backup"]).read_bytes(), b"cover")
        self.assertEqual((self.root / "[E]あさひなぐ" / "表紙.jpg").read_bytes(), b"new")

    def test_zip_of_a_folder(self):
        data = b"".join(self.store.iter_zip("[E]あさひなぐ"))
        archive = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(archive.testzip())
        self.assertEqual(
            sorted(archive.namelist()),
            ["[E]あさひなぐ/01巻/001.jpg", "[E]あさひなぐ/01巻/002.jpg", "[E]あさひなぐ/表紙.jpg"],
        )
        self.assertEqual(archive.read("[E]あさひなぐ/01巻/001.jpg"), b"page1")

    def test_zip_of_everything_skips_internal_folders(self):
        self.store.delete_many(["メモ.txt"])
        names = zipfile.ZipFile(io.BytesIO(b"".join(self.store.iter_zip()))).namelist()
        self.assertTrue(all(TRASH_DIR not in name for name in names))
        self.assertTrue(any(name.endswith("01巻/001.jpg") for name in names))

    def test_zip_is_streamed_in_pieces(self):
        chunks = list(self.store.iter_zip("[E]あさひなぐ"))
        self.assertGreater(len(chunks), 1)

    def test_delete_folder_moves_the_whole_tree(self):
        result = self.store.delete_many(["[E]あさひなぐ"])
        self.assertEqual(result["deleted"][0]["kind"], "folder")
        self.assertFalse((self.root / "[E]あさひなぐ").exists())
        moved = self.root / result["deleted"][0]["trashed"]
        self.assertEqual((moved / "01巻" / "001.jpg").read_bytes(), b"page1")

    def test_delete_file_inside_a_folder(self):
        self.store.delete_many(["[E]あさひなぐ/01巻/001.jpg"])
        self.assertFalse((self.root / "[E]あさひなぐ" / "01巻" / "001.jpg").exists())
        self.assertTrue((self.root / "[E]あさひなぐ" / "01巻" / "002.jpg").exists())

    def test_hard_delete_removes_the_folder(self):
        store = Store(self.root, hard_delete=True)
        store.delete_many(["[E]あさひなぐ"])
        self.assertFalse((self.root / "[E]あさひなぐ").exists())
        self.assertFalse((self.root / TRASH_DIR).exists())

    def test_download_range_inside_a_folder(self):
        data = b"".join(self.store.iter_range("[E]あさひなぐ/01巻/001.jpg", 1, 3))
        self.assertEqual(data, b"age")


if __name__ == "__main__":
    unittest.main()
