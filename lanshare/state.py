"""接続中の端末の記録と、一覧の更新検知用リビジョン。

PC側のセットアップ画面は「iPhoneがつながったらファイル転送画面へ切り替える」ために、
どの端末が接続しているかをサーバに問い合わせる。その状態をここで保持する。
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass

ONLINE_WINDOW = 90.0    # 最終アクセスからこの秒数以内なら「接続中」とみなす
FORGET_AFTER = 15 * 60  # これを過ぎた端末は一覧から消す

_MOBILE_HINTS = (
    ("iPhone", "iPhone", "mobile"),
    ("iPad", "iPad", "mobile"),
    ("iPod", "iPod touch", "mobile"),
    ("Android", "Android", "mobile"),
)
_DESKTOP_HINTS = (
    ("Windows", "Windows PC", "desktop"),
    ("Macintosh", "Mac", "desktop"),
    ("Mac OS X", "Mac", "desktop"),
    ("CrOS", "Chromebook", "desktop"),
    ("Linux", "Linux PC", "desktop"),
)


def describe_user_agent(user_agent: str) -> tuple[str, str]:
    """User-Agentから (表示名, 種別) を推定する。種別は mobile / desktop。"""
    agent = user_agent or ""
    for needle, label, kind in _MOBILE_HINTS:
        if needle in agent:
            return (label, kind)
    for needle, label, kind in _DESKTOP_HINTS:
        if needle in agent:
            return (label, kind)
    return ("端末", "desktop")


@dataclass
class Device:
    id: str
    name: str
    kind: str
    address: str
    connected_at: float
    last_seen: float

    def as_dict(self, now: float) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "address": self.address,
            "connectedAt": self.connected_at,
            "lastSeen": self.last_seen,
            "online": now - self.last_seen <= ONLINE_WINDOW,
        }


class DeviceRegistry:
    """セッショントークン単位で接続中の端末を覚えておく。"""

    def __init__(self):
        self._devices: dict[str, Device] = {}
        self._lock = threading.Lock()

    @staticmethod
    def device_id(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]

    def touch(self, token: str, address: str, user_agent: str, now: float | None = None) -> Device:
        now = time.time() if now is None else now
        name, kind = describe_user_agent(user_agent)
        with self._lock:
            device = self._devices.get(token)
            if device is None:
                device = Device(self.device_id(token), name, kind, address, now, now)
                self._devices[token] = device
            else:
                device.name, device.kind, device.address = name, kind, address
                device.last_seen = now
            self._prune(now)
            return device

    def remove(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._devices.pop(token, None)

    def _prune(self, now: float) -> None:
        for token, device in list(self._devices.items()):
            if now - device.last_seen > FORGET_AFTER:
                del self._devices[token]

    def snapshot(self, current_token: str | None = None, now: float | None = None) -> list[dict]:
        """接続中の端末一覧。``self`` が真の項目が問い合わせ元の端末。"""
        now = time.time() if now is None else now
        with self._lock:
            self._prune(now)
            items = []
            for token, device in self._devices.items():
                entry = device.as_dict(now)
                entry["self"] = token == current_token
                items.append(entry)
        items.sort(key=lambda item: item["connectedAt"])
        return items


class Revision:
    """共有フォルダの更新回数。ブラウザ側の自動再読み込みに使う。"""

    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def bump(self) -> int:
        with self._lock:
            self._value += 1
            return self._value
