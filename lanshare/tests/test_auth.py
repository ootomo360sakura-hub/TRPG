"""PIN認証の検証。"""

import unittest

from lanshare.auth import ATTEMPT_WINDOW, MAX_ATTEMPTS, AuthManager, TooManyAttempts, generate_pin


class GeneratePinTest(unittest.TestCase):
    def test_six_digits(self):
        for _ in range(50):
            pin = generate_pin()
            self.assertEqual(len(pin), 6)
            self.assertTrue(pin.isdigit())


class AuthManagerTest(unittest.TestCase):
    def setUp(self):
        self.auth = AuthManager("123456", ttl=60)

    def test_login_and_session(self):
        token = self.auth.login("123456", "10.0.0.2")
        self.assertTrue(self.auth.is_valid(token))
        self.assertFalse(self.auth.is_valid("bogus"))
        self.assertFalse(self.auth.is_valid(None))

    def test_wrong_pin(self):
        with self.assertRaises(ValueError):
            self.auth.login("000000", "10.0.0.2")

    def test_revoke(self):
        token = self.auth.login("123456", "10.0.0.2")
        self.auth.revoke(token)
        self.assertFalse(self.auth.is_valid(token))

    def test_session_expires(self):
        auth = AuthManager("123456", ttl=10)
        token = auth.login("123456", "10.0.0.2", now=1000.0)
        self.assertTrue(auth.is_valid(token, now=1009.0))
        self.assertFalse(auth.is_valid(token, now=1011.0))

    def test_rate_limit_per_client(self):
        for _ in range(MAX_ATTEMPTS):
            with self.assertRaises(ValueError):
                self.auth.login("999999", "10.0.0.9")
        with self.assertRaises(TooManyAttempts):
            self.auth.login("123456", "10.0.0.9")
        # 別のクライアントは影響を受けない
        self.assertTrue(self.auth.is_valid(self.auth.login("123456", "10.0.0.8")))

    def test_rate_limit_window_resets(self):
        for _ in range(MAX_ATTEMPTS):
            with self.assertRaises(ValueError):
                self.auth.login("999999", "10.0.0.9", now=1000.0)
        later = 1000.0 + ATTEMPT_WINDOW + 1
        token = self.auth.login("123456", "10.0.0.9", now=later)
        self.assertTrue(self.auth.is_valid(token, now=later + 1))

    def test_disabled_auth_accepts_anything(self):
        auth = AuthManager(None, ttl=60, enabled=False)
        self.assertFalse(auth.enabled)
        self.assertTrue(auth.is_valid(None))
        self.assertTrue(auth.is_valid("whatever"))


if __name__ == "__main__":
    unittest.main()
