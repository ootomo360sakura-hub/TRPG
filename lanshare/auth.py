"""PIN認証とセッション管理。

LAN内限定とはいえ、同じWi-Fiにいる他人が共有フォルダを覗ける状態は避けたいので、
起動時に発行する6桁PIN + セッションCookieで保護する。総当たり対策としてIP単位の
試行回数制限を持つ。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

SESSION_COOKIE = "lanshare_session"
MAX_ATTEMPTS = 10
ATTEMPT_WINDOW = 5 * 60


class TooManyAttempts(Exception):
    """PIN入力の失敗が続いた場合に送出する。"""

    def __init__(self, retry_after: int):
        super().__init__(f"試行回数が上限に達しました({retry_after}秒後に再試行)")
        self.retry_after = retry_after


@dataclass
class _Attempts:
    count: int = 0
    first: float = 0.0


def generate_pin(digits: int = 6) -> str:
    """推測されにくい数字PINを生成する。"""
    upper = 10 ** digits
    return str(secrets.randbelow(upper)).zfill(digits)


class AuthManager:
    def __init__(self, pin: str | None, ttl: int, enabled: bool = True):
        self.pin = pin
        self.ttl = ttl
        self.enabled = enabled and bool(pin)
        self._sessions: dict[str, float] = {}
        self._attempts: dict[str, _Attempts] = {}

    # --- セッション ---

    def _purge(self, now: float) -> None:
        for token, expiry in list(self._sessions.items()):
            if expiry <= now:
                del self._sessions[token]

    def issue(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        self._purge(now)
        token = secrets.token_urlsafe(24)
        self._sessions[token] = now + self.ttl
        return token

    def is_valid(self, token: str | None, now: float | None = None) -> bool:
        if not self.enabled:
            return True
        if not token:
            return False
        now = time.time() if now is None else now
        expiry = self._sessions.get(token)
        if expiry is None:
            return False
        if expiry <= now:
            del self._sessions[token]
            return False
        return True

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    # --- PIN照合 ---

    def login(self, pin: str, client: str, now: float | None = None) -> str:
        """PINを照合し、成功したらセッショントークンを返す。"""
        now = time.time() if now is None else now
        record = self._attempts.get(client)
        if record and now - record.first > ATTEMPT_WINDOW:
            record = None
            self._attempts.pop(client, None)
        if record and record.count >= MAX_ATTEMPTS:
            raise TooManyAttempts(int(ATTEMPT_WINDOW - (now - record.first)) + 1)

        if not self.enabled:
            return self.issue(now)

        if self.pin and secrets.compare_digest(str(pin), self.pin):
            self._attempts.pop(client, None)
            return self.issue(now)

        record = record or _Attempts(0, now)
        record.count += 1
        self._attempts[client] = record
        raise ValueError("PINが違います")
