"""日時の解釈と、募集記事Embedの組み立て。"""

import calendar
import os
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import discord

from store import EXTRA_FIELDS, Recruitment

TZ = ZoneInfo(os.getenv("BOT_TIMEZONE", "Asia/Tokyo"))

JOIN_EMOJI = "✋"
INTEREST_EMOJI = "👀"

WEEK = timedelta(days=7)
DAY = timedelta(days=1)

OVER_CAPACITY_NOTE = "※定員を超えた場合はGM判断となります。"

COLOR_OPEN = discord.Color.green()
COLOR_FULL = discord.Color.orange()
COLOR_CANCELLED = discord.Color.dark_grey()

REMINDER_HOUR = 9  # リマインドは対象日の午前9時に送る

TIME_RE = re.compile(r"^\s*(\d{1,2})\s*(?:[:：時]\s*(\d{1,2})?\s*分?)?\s*[〜~～-]?\s*$")
TIME_FORMAT_HINT = "例: 21:00 ・ 21時 ・ 2130"
WEEKDAYS = "月火水木金土日"


def parse_time(text: str) -> time:
    """開始時刻の入力(21:00 / 21時 / 2130 など)を解釈する。"""
    text = text.translate(str.maketrans("０１２３４５６７８９：", "0123456789:")).strip()
    if re.fullmatch(r"\d{3,4}", text):
        text = f"{text[:-2]}:{text[-2:]}"
    m = TIME_RE.match(text)
    if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2) or 0) <= 59):
        raise ValueError(f"開始時刻を読み取れませんでした。{TIME_FORMAT_HINT}")
    return time(int(m.group(1)), int(m.group(2) or 0))


def combine(day: date, start_time: time, now: datetime | None = None) -> datetime:
    """カレンダーで選んだ日付と入力した時刻を合わせる。過去なら ValueError。"""
    dt = datetime.combine(day, start_time, tzinfo=TZ)
    if dt <= (now or datetime.now(TZ)):
        raise ValueError("過去の日時は指定できません。")
    return dt


def reminder_times(start_at: int) -> tuple[int, int]:
    """(1週間前リマインド, 前日リマインド)の送信時刻。どちらも対象日の午前9時。"""
    start_day = datetime.fromtimestamp(start_at, TZ).date()

    def at_nine(d: date) -> int:
        return int(datetime.combine(d, time(REMINDER_HOUR), tzinfo=TZ).timestamp())

    return at_nine(start_day - WEEK), at_nine(start_day - DAY)


def format_day(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def calendar_text(year: int, month: int, today: date) -> str:
    """カレンダー表示用のテキスト(日曜始まり)。今日より前の日は「・」で表す。"""
    lines = [" 日 月 火 水 木 金 土"]
    cal = calendar.Calendar(firstweekday=6)
    for week in cal.monthdayscalendar(year, month):
        cells = []
        for d in week:
            if d == 0:
                cells.append("   ")
            elif date(year, month, d) < today:
                cells.append(" ・")  # 全角1文字=半角2文字分で3桁に揃える
            else:
                cells.append(f"{d:3d}")
        lines.append("".join(cells))
    return "```\n" + "\n".join(lines) + "\n```"


def mentions(ids: list[int]) -> str:
    return "\n".join(f"<@{uid}>" for uid in ids)


def build_embed(rec: Recruitment) -> discord.Embed:
    members = rec.participants[: rec.capacity]
    over = rec.participants[rec.capacity:]

    if rec.cancelled:
        title, color = f"【募集取消】{rec.title}", COLOR_CANCELLED
    elif rec.is_full:
        title, color = f"【満員・締切】{rec.title}", COLOR_FULL
    else:
        title, color = f"【TRPG募集】{rec.title}", COLOR_OPEN

    description = rec.details.strip()
    if not rec.cancelled:
        description = f"{description}\n\n{OVER_CAPACITY_NOTE}".strip()
    embed = discord.Embed(title=title, description=description, color=color)

    embed.add_field(name="GM", value=f"<@{rec.gm_id}>", inline=True)
    when = f"<t:{rec.start_at}:F>\n(<t:{rec.start_at}:R>)" if rec.start_at else "未設定(📅 日時を選ぶ)"
    embed.add_field(name="日時", value=when, inline=True)
    embed.add_field(name="定員", value=f"{rec.capacity}名", inline=True)
    for key, label in EXTRA_FIELDS.items():
        if rec.extras.get(key):
            embed.add_field(name=label, value=rec.extras[key], inline=True)
    embed.add_field(
        name="リマインド",
        value="あり(1週間前・前日の午前9時に参加者へ通知)" if rec.reminder else "なし",
        inline=False,
    )

    status = " (満員)" if rec.is_full else ""
    embed.add_field(
        name=f"{JOIN_EMOJI} 参加希望 {len(members)}/{rec.capacity}{status}",
        value=mentions(members) or "まだいません",
        inline=False,
    )
    if over:
        embed.add_field(name=f"定員超過 {len(over)}名(GM判断)", value=mentions(over), inline=False)
    embed.add_field(
        name=f"{INTEREST_EMOJI} 興味あり {len(rec.interested)}名",
        value=mentions(rec.interested) or "まだいません",
        inline=False,
    )

    if rec.cancelled:
        embed.set_footer(text="この募集は取り消されました")
    elif rec.is_full:
        embed.set_footer(
            text=f"参加希望は締め切りました(以降の{JOIN_EMOJI}は定員超過・GM判断) / {INTEREST_EMOJI} 興味ありは引き続き受付中"
        )
    else:
        embed.set_footer(text=f"{JOIN_EMOJI} 参加希望 / {INTEREST_EMOJI} 興味あり ― リアクションを外すと取消")
    return embed
