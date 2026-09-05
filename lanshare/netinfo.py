"""ネットワーク情報(LAN内のIPアドレス取得、接続元の判定)。"""

from __future__ import annotations

import ipaddress
import socket
import time


_OWN_ADDRESSES: set[str] | None = None
_OWN_ADDRESSES_AT = 0.0
_OWN_ADDRESSES_TTL = 60.0  # IPが変わっても1分で追従する


def primary_address() -> str | None:
    """デフォルトルート側のIPv4アドレスを返す(実際の通信は行わない)。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1、UDPなのでパケットは出ない
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def lan_addresses() -> list[str]:
    """このPCがLAN内で持っているIPv4アドレスの一覧(プライベートIP優先)。"""
    found: list[str] = []
    primary = primary_address()
    if primary:
        found.append(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found:
                found.append(address)
    except OSError:
        pass

    def sort_key(address: str) -> tuple[int, str]:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return (3, address)
        if ip.is_loopback:
            return (2, address)
        return (0 if ip.is_private else 1, address)

    return [a for a in sorted(found, key=sort_key) if not a.startswith("169.254.")]


def own_addresses() -> set[str]:
    """このPC自身を指すアドレスの集合(ループバック + LAN側のIP)。"""
    global _OWN_ADDRESSES, _OWN_ADDRESSES_AT
    now = time.monotonic()
    if _OWN_ADDRESSES is None or now - _OWN_ADDRESSES_AT > _OWN_ADDRESSES_TTL:
        _OWN_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"} | set(lan_addresses())
        _OWN_ADDRESSES_AT = now
    return _OWN_ADDRESSES


def is_own_address(address: str) -> bool:
    """接続元がこのPC自身かどうか(ブラウザをPCで開いた場合)。"""
    if not address:
        return False
    if address in own_addresses():
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return str(ip.ipv4_mapped) in own_addresses()
    return bool(ip.is_loopback)


def is_local_client(address: str) -> bool:
    """接続元がプライベートIP・ループバック・リンクローカルかどうか。"""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
