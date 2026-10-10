"""募集データの保存(SQLite)。

リマインドを送るには開催日時・参加者を覚えておく必要があるので、
募集記事1件 = 1行としてDBに保存する。
"""

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from pathlib import Path

STATUS_OPEN = "open"
STATUS_CANCELLED = "cancelled"

# 追加項目(任意入力)。キー → 表示名
EXTRA_FIELDS = {
    "system": "システム",
    "skills": "推奨技能",
    "playtime": "想定プレイ時間",
    "style": "形式(ボイス/テキスト)",
    "notes": "備考",
}


@dataclass
class Recruitment:
    message_id: int
    channel_id: int
    guild_id: int
    gm_id: int
    title: str
    start_at: int  # UNIX秒
    capacity: int
    details: str = ""
    extras: dict[str, str] = field(default_factory=dict)
    reminder: bool = True
    status: str = STATUS_OPEN
    participants: list[int] = field(default_factory=list)  # 参加希望(リアクション順)
    interested: list[int] = field(default_factory=list)  # 興味あり
    week_sent: bool = False
    day_sent: bool = False

    @property
    def is_full(self) -> bool:
        return len(self.participants) >= self.capacity

    @property
    def cancelled(self) -> bool:
        return self.status == STATUS_CANCELLED


SCHEMA = """
CREATE TABLE IF NOT EXISTS recruitments (
    message_id   INTEGER PRIMARY KEY,
    channel_id   INTEGER NOT NULL,
    guild_id     INTEGER NOT NULL,
    gm_id        INTEGER NOT NULL,
    title        TEXT    NOT NULL,
    start_at     INTEGER NOT NULL,
    capacity     INTEGER NOT NULL,
    details      TEXT    NOT NULL DEFAULT '',
    extras       TEXT    NOT NULL DEFAULT '{}',
    reminder     INTEGER NOT NULL DEFAULT 1,
    status       TEXT    NOT NULL DEFAULT 'open',
    participants TEXT    NOT NULL DEFAULT '[]',
    interested   TEXT    NOT NULL DEFAULT '[]',
    week_sent    INTEGER NOT NULL DEFAULT 0,
    day_sent     INTEGER NOT NULL DEFAULT 0
)
"""

JSON_COLUMNS = ("extras", "participants", "interested")
BOOL_COLUMNS = ("reminder", "week_sent", "day_sent")


class Store:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def _from_row(self, row: sqlite3.Row) -> Recruitment:
        data = dict(row)
        for col in JSON_COLUMNS:
            data[col] = json.loads(data[col])
        for col in BOOL_COLUMNS:
            data[col] = bool(data[col])
        return Recruitment(**data)

    def save(self, rec: Recruitment) -> None:
        data = asdict(rec)
        for col in JSON_COLUMNS:
            data[col] = json.dumps(data[col], ensure_ascii=False)
        for col in BOOL_COLUMNS:
            data[col] = int(data[col])
        cols = ", ".join(data)
        marks = ", ".join(f":{c}" for c in data)
        self.conn.execute(f"INSERT OR REPLACE INTO recruitments ({cols}) VALUES ({marks})", data)
        self.conn.commit()

    def get(self, message_id: int) -> Recruitment | None:
        row = self.conn.execute("SELECT * FROM recruitments WHERE message_id = ?", (message_id,)).fetchone()
        return self._from_row(row) if row else None

    def delete(self, message_id: int) -> None:
        self.conn.execute("DELETE FROM recruitments WHERE message_id = ?", (message_id,))
        self.conn.commit()

    def pending_reminders(self, now: int) -> list[Recruitment]:
        """リマインド対象(リマインドON・未取消・開催前・未送信あり)を返す。"""
        rows = self.conn.execute(
            """SELECT * FROM recruitments
               WHERE reminder = 1 AND status = 'open' AND start_at > ?
                 AND (week_sent = 0 OR day_sent = 0)""",
            (now,),
        ).fetchall()
        return [self._from_row(r) for r in rows]
