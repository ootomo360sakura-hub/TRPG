"""サーバ設定。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_ROOT = "shared"
DEFAULT_SESSION_TTL = 12 * 60 * 60


@dataclass
class ServerConfig:
    root: Path
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    pin: str | None = None
    require_auth: bool = True
    allow_any_client: bool = False
    trust_local: bool = True  # このPC自身からのアクセスはPINなしで通す
    on_conflict: str = "rename"
    hard_delete: bool = False
    session_ttl: int = DEFAULT_SESSION_TTL
    quiet: bool = False
    extra_urls: list[str] = field(default_factory=list)
