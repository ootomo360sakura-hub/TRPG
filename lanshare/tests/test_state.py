"""接続端末の記録とリビジョンの検証。"""

import unittest

from lanshare.state import FORGET_AFTER, ONLINE_WINDOW, DeviceRegistry, Revision, describe_user_agent

IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


class UserAgentTest(unittest.TestCase):
    def test_known_devices(self):
        self.assertEqual(describe_user_agent(IPHONE_UA), ("iPhone", "mobile"))
        self.assertEqual(describe_user_agent(WINDOWS_UA), ("Windows PC", "desktop"))
        self.assertEqual(describe_user_agent("... (iPad; CPU OS 17_5) ...")[1], "mobile")
        self.assertEqual(describe_user_agent("... (Linux; Android 14; Pixel) ...")[1], "mobile")
        self.assertEqual(describe_user_agent("... (Macintosh; Intel Mac OS X 10_15_7) ...")[0], "Mac")

    def test_unknown_agent(self):
        self.assertEqual(describe_user_agent(""), ("端末", "desktop"))
        self.assertEqual(describe_user_agent("curl/8.4.0"), ("端末", "desktop"))


class DeviceRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()

    def test_touch_creates_then_updates(self):
        first = self.registry.touch("token-a", "192.168.1.5", IPHONE_UA, now=100.0)
        second = self.registry.touch("token-a", "192.168.1.5", IPHONE_UA, now=140.0)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.connected_at, 100.0)
        self.assertEqual(second.last_seen, 140.0)
        self.assertEqual(len(self.registry.snapshot(now=140.0)), 1)

    def test_snapshot_marks_self_and_online(self):
        self.registry.touch("pc", "192.168.1.2", WINDOWS_UA, now=100.0)
        self.registry.touch("phone", "192.168.1.5", IPHONE_UA, now=101.0)
        devices = self.registry.snapshot("pc", now=102.0)
        by_name = {device["name"]: device for device in devices}
        self.assertTrue(by_name["Windows PC"]["self"])
        self.assertFalse(by_name["iPhone"]["self"])
        self.assertEqual(by_name["iPhone"]["kind"], "mobile")
        self.assertTrue(all(device["online"] for device in devices))

    def test_offline_after_window(self):
        self.registry.touch("phone", "192.168.1.5", IPHONE_UA, now=100.0)
        devices = self.registry.snapshot(now=100.0 + ONLINE_WINDOW + 1)
        self.assertFalse(devices[0]["online"])

    def test_forgotten_after_long_silence(self):
        self.registry.touch("phone", "192.168.1.5", IPHONE_UA, now=100.0)
        self.assertEqual(self.registry.snapshot(now=100.0 + FORGET_AFTER + 1), [])

    def test_remove(self):
        self.registry.touch("phone", "192.168.1.5", IPHONE_UA, now=100.0)
        self.registry.remove("phone")
        self.registry.remove(None)
        self.assertEqual(self.registry.snapshot(now=101.0), [])

    def test_ids_differ_per_token(self):
        a = self.registry.touch("token-a", "192.168.1.5", IPHONE_UA)
        b = self.registry.touch("token-b", "192.168.1.6", IPHONE_UA)
        self.assertNotEqual(a.id, b.id)
        self.assertNotIn("token-a", a.id)

    def test_snapshot_sorted_by_connection_order(self):
        self.registry.touch("first", "192.168.1.2", WINDOWS_UA, now=100.0)
        self.registry.touch("second", "192.168.1.5", IPHONE_UA, now=200.0)
        names = [device["name"] for device in self.registry.snapshot(now=201.0)]
        self.assertEqual(names, ["Windows PC", "iPhone"])


class RevisionTest(unittest.TestCase):
    def test_bump(self):
        revision = Revision()
        self.assertEqual(revision.value, 0)
        self.assertEqual(revision.bump(), 1)
        revision.bump()
        self.assertEqual(revision.value, 2)


if __name__ == "__main__":
    unittest.main()
