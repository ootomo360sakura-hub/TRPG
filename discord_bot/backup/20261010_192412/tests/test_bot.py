"""Discordに接続せずに確認できるロジックのテスト。 python3 -m pytest tests"""

import asyncio
import os
import sys
import tempfile
import time
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest

import bot as botmod
from render import TZ, build_embed, parse_datetime
from store import Recruitment, Store

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=TZ)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026/10/20 21:00", datetime(2026, 10, 20, 21, 0, tzinfo=TZ)),
        ("10/20 21:30", datetime(2026, 10, 20, 21, 30, tzinfo=TZ)),
        ("10月20日 21時", datetime(2026, 10, 20, 21, 0, tzinfo=TZ)),
        ("10/20(火) 21:00〜", datetime(2026, 10, 20, 21, 0, tzinfo=TZ)),
        ("１０／２０ ２１：００", datetime(2026, 10, 20, 21, 0, tzinfo=TZ)),
        ("1/5 20:00", datetime(2027, 1, 5, 20, 0, tzinfo=TZ)),  # 年省略で過ぎた日付は翌年
    ],
)
def test_parse_datetime(text, expected):
    assert parse_datetime(text, NOW) == expected


@pytest.mark.parametrize("text", ["来週の土曜", "2026/2/30 21:00", "2026/10/1 21:00"])
def test_parse_datetime_invalid(text):
    with pytest.raises(ValueError):
        parse_datetime(text, NOW)


def make_rec(**kw):
    base = dict(message_id=1, channel_id=2, guild_id=3, gm_id=10, title="狂気山脈",
                start_at=int(time.time()) + 30 * 86400, capacity=2)
    base.update(kw)
    return Recruitment(**base)


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "x.db")
    rec = make_rec(extras={"system": "CoC6版"}, participants=[5, 3], interested=[7])
    store.save(rec)
    assert store.get(1) == rec


def test_embed_full_and_over_capacity():
    rec = make_rec(participants=[5, 3, 9], interested=[7], extras={"system": "CoC6版"})
    embed = build_embed(rec)
    assert embed.title.startswith("【満員・締切】")
    assert "GM判断" in embed.description
    names = [f.name for f in embed.fields]
    assert "システム" in names and any(n.startswith("定員超過") for n in names)


class FakeReaction:
    def __init__(self, emoji, ids, me=True):
        self.emoji, self.ids, self.me = emoji, ids, me

    async def users(self):
        for uid in self.ids:
            yield SimpleNamespace(id=uid, bot=uid == 999)


def run_sync(rec, join, interest):
    b = botmod.bot
    b.store.save(rec)
    message = SimpleNamespace(reactions=[FakeReaction("✋", join), FakeReaction("👀", interest)])
    saved = {}

    async def fake_refresh(r, m=None):
        saved["rec"] = r

    b.save_and_refresh = fake_refresh
    asyncio.run(b.sync_reactions(rec, message))
    return saved.get("rec")


def test_sync_keeps_order_and_excludes_gm_and_bots():
    rec = make_rec(participants=[5])
    out = run_sync(rec, join=[3, 5, 10, 999], interest=[3, 7])
    assert out.participants == [5, 3]  # 既存の5が先、GM(10)とBot(999)は除外
    assert out.interested == [7]  # 参加希望の3は興味ありから除く


def test_reminders():
    b = botmod.bot
    sent = []

    async def fake_notify(rec, text, include_gm=False):
        sent.append(text)

    b.notify = fake_notify
    now = int(time.time())
    b.store.save(make_rec(message_id=100, start_at=now + 6 * 86400))  # 1週間以内 → 1週間前分
    b.store.save(make_rec(message_id=101, start_at=now + 3600))  # 前日分のみ
    b.store.save(make_rec(message_id=102, start_at=now + 20 * 86400))  # まだ
    b.store.save(make_rec(message_id=103, start_at=now + 3600, reminder=False))  # リマインドなし
    asyncio.run(b.reminder_loop.coro(b))
    assert len(sent) == 2 and any("1週間後" in s for s in sent) and any("明日" in s for s in sent)
    assert b.store.get(101).week_sent and b.store.get(101).day_sent
    sent.clear()
    asyncio.run(b.reminder_loop.coro(b))
    assert sent == []  # 二重送信しない
