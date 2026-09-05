"""ネットワーク判定の検証。"""

import unittest

from lanshare.netinfo import is_local_client, is_own_address, lan_addresses, own_addresses


class IsLocalClientTest(unittest.TestCase):
    def test_private_and_loopback_allowed(self):
        for address in ("127.0.0.1", "192.168.1.10", "10.0.0.5", "172.16.3.4",
                        "::1", "fe80::1", "::ffff:192.168.0.7"):
            with self.subTest(address=address):
                self.assertTrue(is_local_client(address))

    def test_public_addresses_blocked(self):
        for address in ("8.8.8.8", "1.1.1.1", "93.184.216.34", "2001:4860:4860::8888", "", "not-an-ip"):
            with self.subTest(address=address):
                self.assertFalse(is_local_client(address))


class IsOwnAddressTest(unittest.TestCase):
    def test_loopback_is_this_pc(self):
        for address in ("127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1"):
            with self.subTest(address=address):
                self.assertTrue(is_own_address(address))

    def test_own_lan_address_is_this_pc(self):
        for address in own_addresses():
            with self.subTest(address=address):
                self.assertTrue(is_own_address(address))

    def test_other_devices_are_not(self):
        for address in ("192.168.99.250", "10.99.99.99", "", "not-an-ip"):
            with self.subTest(address=address):
                self.assertFalse(is_own_address(address))


class LanAddressesTest(unittest.TestCase):
    def test_returns_ipv4_strings(self):
        addresses = lan_addresses()
        self.assertIsInstance(addresses, list)
        for address in addresses:
            self.assertRegex(address, r"^\d+\.\d+\.\d+\.\d+$")
            self.assertFalse(address.startswith("169.254."))


if __name__ == "__main__":
    unittest.main()
