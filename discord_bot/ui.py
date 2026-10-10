"""募集の作成・編集・取消に使うフォーム(モーダル)・カレンダー・ボタン。"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Awaitable, Callable

import discord

from render import (
    INTEREST_EMOJI,
    JOIN_EMOJI,
    TIME_FORMAT_HINT,
    TZ,
    build_embed,
    calendar_text,
    combine,
    format_day,
    parse_time,
    reminder_times,
)
from store import EXTRA_FIELDS, STATUS_CANCELLED, Recruitment

if TYPE_CHECKING:
    from bot import RecruitBot

GM_MENU_ID = "recruit:gm_menu"
CALENDAR_MONTHS_AHEAD = 12  # カレンダーで選べるのは今月から12か月先まで

OnStartPicked = Callable[[discord.Interaction, int], Awaitable[None]]


def reset_reminder_flags(rec: Recruitment) -> None:
    """すでに送信時刻(対象日の午前9時)を過ぎているリマインドは「送信済み」扱いにする。"""
    now = time.time()
    week_at, day_at = reminder_times(rec.start_at)
    rec.week_sent = now >= week_at
    rec.day_sent = now >= day_at


def parse_capacity(text: str) -> int:
    text = text.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if not text.isdigit() or not 1 <= int(text) <= 30:
        raise ValueError("定員は1〜30の数字で入力してください。")
    return int(text)


# ---------------------------------------------------------------- フォーム


class BasicModal(discord.ui.Modal):
    """基本項目(タイトル・定員・募集内容)。作成と編集で共用。開催日時はカレンダーで別に選ぶ。"""

    def __init__(self, rec: Recruitment | None = None) -> None:
        super().__init__(title="募集内容の編集" if rec else "TRPG募集を作成", timeout=900)
        self.rec = rec
        self.title_input = discord.ui.TextInput(
            label="タイトル(シナリオ名・卓名)", max_length=100, default=rec.title if rec else None
        )
        self.capacity_input = discord.ui.TextInput(
            label="定員(GMを除くプレイヤー人数)",
            placeholder="例: 4",
            max_length=2,
            default=str(rec.capacity) if rec else None,
        )
        self.details_input = discord.ui.TextInput(
            label="募集内容・詳細(任意)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1500,
            default=rec.details if rec else None,
        )
        for item in (self.title_input, self.capacity_input, self.details_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            capacity = parse_capacity(self.capacity_input.value)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return
        title, details = self.title_input.value.strip(), self.details_input.value

        if self.rec is None:
            # 新規作成: 続けてカレンダーで開催日を選んでもらう
            rec = Recruitment(
                message_id=0,
                channel_id=interaction.channel_id,
                guild_id=interaction.guild_id,
                gm_id=interaction.user.id,
                title=title,
                start_at=0,
                capacity=capacity,
                details=details,
            )
            draft = DraftView(rec)

            async def on_picked(picked: discord.Interaction, start_at: int) -> None:
                rec.start_at = start_at
                await picked.response.edit_message(content=draft.guide_text(), embed=build_embed(rec), view=draft)

            calendar_view = CalendarView(on_picked)
            await interaction.response.send_message(
                content="**開催日を選んでください**(このあと開始時刻を入力します)",
                embed=calendar_view.embed(),
                view=calendar_view,
                ephemeral=True,
            )
            return

        bot: RecruitBot = interaction.client
        rec = bot.store.get(self.rec.message_id)
        if rec is None or rec.cancelled:
            await interaction.response.send_message("この募集はもう編集できません。", ephemeral=True)
            return
        rec.title, rec.capacity, rec.details = title, capacity, details
        await interaction.response.defer(ephemeral=True)
        await bot.save_and_refresh(rec)
        await interaction.followup.send("✅ 募集内容を更新しました。", ephemeral=True)


class TimeModal(discord.ui.Modal):
    """カレンダーで日付を選んだあとに出る、開始時刻の入力フォーム。"""

    def __init__(self, day: date, calendar_view: CalendarView) -> None:
        super().__init__(title=f"{format_day(day)} の開始時刻", timeout=600)
        self.day = day
        self.calendar_view = calendar_view
        self.time_input = discord.ui.TextInput(label="開始時刻", placeholder=TIME_FORMAT_HINT, max_length=10)
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            start = combine(self.day, parse_time(self.time_input.value))
        except ValueError as e:
            # カレンダーを描き直して(プルダウンの選択をリセットして)選び直してもらう
            self.calendar_view.render()
            await interaction.response.edit_message(
                content=f"⚠️ {e} もう一度日付を選んでください。",
                embed=self.calendar_view.embed(),
                view=self.calendar_view,
            )
            return
        await self.calendar_view.on_picked(interaction, int(start.timestamp()))


class CalendarView(discord.ui.View):
    """月カレンダーを表示し、プルダウンから開催日を選ばせる(Discordに日付ピッカーがないための代用)。"""

    def __init__(self, on_picked: OnStartPicked, initial: date | None = None) -> None:
        super().__init__(timeout=900)
        self.on_picked = on_picked
        self.today = datetime.now(TZ).date()
        base = initial if initial and initial >= self.today else self.today
        self.year, self.month = base.year, base.month
        self.render()

    def month_index(self) -> int:
        return (self.year - self.today.year) * 12 + (self.month - self.today.month)

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title=f"📅 {self.year}年{self.month}月",
            description=calendar_text(self.year, self.month, self.today),
            color=discord.Color.blurple(),
        )

    def render(self) -> None:
        self.clear_items()

        prev_btn = discord.ui.Button(label="◀ 前の月", row=0, disabled=self.month_index() <= 0)
        next_btn = discord.ui.Button(label="次の月 ▶", row=0, disabled=self.month_index() >= CALENDAR_MONTHS_AHEAD)
        prev_btn.callback = lambda i: self.shift(i, -1)
        next_btn.callback = lambda i: self.shift(i, +1)
        self.add_item(prev_btn)
        self.add_item(next_btn)

        # プルダウンは1つ25件までなので、前半(1〜15日)と後半(16日〜末日)に分ける
        days = []
        d = date(self.year, self.month, 1)
        while d.month == self.month:
            if d >= self.today:
                days.append(d)
            d = date.fromordinal(d.toordinal() + 1)
        halves = [
            ("1〜15日から選ぶ", [x for x in days if x.day <= 15]),
            ("16日〜月末から選ぶ", [x for x in days if x.day > 15]),
        ]
        for row, (placeholder, choices) in enumerate(halves, start=1):
            if not choices:
                continue
            select = discord.ui.Select(
                placeholder=placeholder,
                row=row,
                options=[discord.SelectOption(label=format_day(x), value=x.isoformat()) for x in choices],
            )
            select.callback = self.make_pick(select)
            self.add_item(select)

    async def shift(self, interaction: discord.Interaction, delta: int) -> None:
        total = self.year * 12 + (self.month - 1) + delta
        self.year, self.month = divmod(total, 12)
        self.month += 1
        self.render()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    def make_pick(self, select: discord.ui.Select):
        async def pick(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(TimeModal(date.fromisoformat(select.values[0]), self))

        return pick


class ExtrasModal(discord.ui.Modal):
    """任意の追加項目。ボタンを押したときだけ表示する。"""

    def __init__(self, rec: Recruitment, on_done) -> None:
        super().__init__(title="追加項目(すべて任意)", timeout=900)
        self.rec = rec
        self.on_done = on_done
        self.inputs: dict[str, discord.ui.TextInput] = {}
        placeholders = {
            "system": "例: クトゥルフ神話TRPG 6版",
            "skills": "例: 目星・図書館・聞き耳",
            "playtime": "例: 4〜5時間(1回)",
            "style": "例: ボイスセッション(聞き専可)",
            "notes": "例: 初心者歓迎・ロスト率低め",
        }
        for key, label in EXTRA_FIELDS.items():
            item = discord.ui.TextInput(
                label=label,
                placeholder=placeholders[key],
                required=False,
                max_length=200,
                default=rec.extras.get(key) or None,
            )
            self.inputs[key] = item
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        extras = {k: v.value.strip() for k, v in self.inputs.items() if v.value.strip()}
        await self.on_done(interaction, extras)


# ---------------------------------------------------------------- 投稿前の下書き


class DraftView(discord.ui.View):
    """/募集 の入力後に本人だけに表示される下書きパネル。"""

    def __init__(self, rec: Recruitment) -> None:
        super().__init__(timeout=900)
        self.rec = rec
        self.update_reminder_button()

    def guide_text(self) -> str:
        return (
            "**下書きプレビュー**(あなたにだけ表示されています)\n"
            "必要なら「追加項目を入力」で項目を足し、リマインドの有無を決めてから「投稿する」を押してください。"
        )

    @discord.ui.button(label="日時を変更", emoji="📅", style=discord.ButtonStyle.secondary)
    async def change_date(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def on_picked(picked: discord.Interaction, start_at: int) -> None:
            self.rec.start_at = start_at
            await picked.response.edit_message(content=self.guide_text(), embed=build_embed(self.rec), view=self)

        initial = datetime.fromtimestamp(self.rec.start_at, TZ).date() if self.rec.start_at else None
        calendar_view = CalendarView(on_picked, initial)
        await interaction.response.edit_message(
            content="**開催日を選んでください**", embed=calendar_view.embed(), view=calendar_view
        )

    def update_reminder_button(self) -> None:
        self.toggle_reminder.label = f"リマインド: {'あり' if self.rec.reminder else 'なし'}"
        self.toggle_reminder.style = discord.ButtonStyle.success if self.rec.reminder else discord.ButtonStyle.secondary

    @discord.ui.button(label="追加項目を入力", emoji="📝", style=discord.ButtonStyle.secondary)
    async def add_extras(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def on_done(modal_interaction: discord.Interaction, extras: dict[str, str]) -> None:
            self.rec.extras = extras
            await modal_interaction.response.edit_message(embed=build_embed(self.rec), view=self)

        await interaction.response.send_modal(ExtrasModal(self.rec, on_done))

    @discord.ui.button(label="リマインド", emoji="🔔")
    async def toggle_reminder(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.rec.reminder = not self.rec.reminder
        self.update_reminder_button()
        await interaction.response.edit_message(embed=build_embed(self.rec), view=self)

    @discord.ui.button(label="投稿する", emoji="📣", style=discord.ButtonStyle.primary)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: RecruitBot = interaction.client
        if self.rec.start_at <= time.time():
            await interaction.response.send_message("⚠️ 開催日時が過ぎています。「日時を変更」から選び直してください。", ephemeral=True)
            return
        await interaction.response.edit_message(content="投稿中…", embed=None, view=None)
        reset_reminder_flags(self.rec)
        message = await interaction.channel.send(embed=build_embed(self.rec), view=GmMenuView())
        rec = replace(self.rec, message_id=message.id, channel_id=message.channel.id)
        bot.store.save(rec)
        await message.add_reaction(JOIN_EMOJI)
        await message.add_reaction(INTEREST_EMOJI)
        await interaction.edit_original_response(content=f"✅ 募集を投稿しました: {message.jump_url}")
        self.stop()

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.danger)
    async def discard(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="下書きを破棄しました。", embed=None, view=None)
        self.stop()


# ---------------------------------------------------------------- 投稿後のGMメニュー


class GmMenuView(discord.ui.View):
    """募集記事に付く常設ボタン。Bot再起動後も押せるよう timeout=None + 固定custom_id。"""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="GMメニュー", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id=GM_MENU_ID)
    async def open_menu(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: RecruitBot = interaction.client
        rec = bot.store.get(interaction.message.id)
        if rec is None or rec.cancelled:
            await interaction.response.send_message("この募集はもう操作できません。", ephemeral=True)
            return
        if interaction.user.id != rec.gm_id:
            await interaction.response.send_message("GMメニューは募集を投稿した人だけが使えます。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**{rec.title}** のGMメニュー", view=GmPanel(rec.message_id), ephemeral=True
        )


class GmPanel(discord.ui.View):
    """GM本人にだけ表示される操作パネル。"""

    def __init__(self, message_id: int) -> None:
        super().__init__(timeout=600)
        self.message_id = message_id

    async def load(self, interaction: discord.Interaction) -> Recruitment | None:
        rec = interaction.client.store.get(self.message_id)
        if rec is None or rec.cancelled:
            await interaction.response.send_message("この募集はもう操作できません。", ephemeral=True)
            return None
        return rec

    @discord.ui.button(label="内容を編集", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit_basic(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if rec := await self.load(interaction):
            await interaction.response.send_modal(BasicModal(rec))

    @discord.ui.button(label="日時を変更", emoji="📅", style=discord.ButtonStyle.primary)
    async def edit_date(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        rec = await self.load(interaction)
        if rec is None:
            return

        async def on_picked(picked: discord.Interaction, start_at: int) -> None:
            bot: RecruitBot = picked.client
            latest = bot.store.get(self.message_id)
            if latest is None or latest.cancelled:
                await picked.response.edit_message(content="この募集はもう編集できません。", embed=None, view=None)
                return
            latest.start_at = start_at
            reset_reminder_flags(latest)  # 新しい日時に合わせてリマインドを組み直す
            await picked.response.edit_message(content="更新中…", embed=None, view=None)
            await bot.save_and_refresh(latest)
            await picked.edit_original_response(content=f"✅ 開催日時を <t:{start_at}:F> に変更しました。")

        calendar_view = CalendarView(on_picked, datetime.fromtimestamp(rec.start_at, TZ).date())
        await interaction.response.send_message(
            content="**新しい開催日を選んでください**", embed=calendar_view.embed(), view=calendar_view, ephemeral=True
        )

    @discord.ui.button(label="追加項目を編集", emoji="📝", style=discord.ButtonStyle.secondary)
    async def edit_extras(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        rec = await self.load(interaction)
        if rec is None:
            return

        async def on_done(modal_interaction: discord.Interaction, extras: dict[str, str]) -> None:
            bot: RecruitBot = modal_interaction.client
            latest = bot.store.get(self.message_id)
            if latest is None or latest.cancelled:
                await modal_interaction.response.send_message("この募集はもう編集できません。", ephemeral=True)
                return
            latest.extras = extras
            await modal_interaction.response.defer(ephemeral=True)
            await bot.save_and_refresh(latest)
            await modal_interaction.followup.send("✅ 追加項目を更新しました。", ephemeral=True)

        await interaction.response.send_modal(ExtrasModal(rec, on_done))

    @discord.ui.button(label="リマインド切替", emoji="🔔", style=discord.ButtonStyle.secondary)
    async def toggle_reminder(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        rec = await self.load(interaction)
        if rec is None:
            return
        rec.reminder = not rec.reminder
        if rec.reminder:
            reset_reminder_flags(rec)
        await interaction.response.defer(ephemeral=True)
        await interaction.client.save_and_refresh(rec)
        await interaction.followup.send(
            f"🔔 リマインドを **{'あり' if rec.reminder else 'なし'}** にしました。", ephemeral=True
        )

    @discord.ui.button(label="募集を取り消す", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await self.load(interaction):
            await interaction.response.send_message(
                "本当にこの募集を取り消しますか?参加希望者には取消のお知らせが送られます。",
                view=CancelConfirmView(self.message_id),
                ephemeral=True,
            )


class CancelConfirmView(discord.ui.View):
    def __init__(self, message_id: int) -> None:
        super().__init__(timeout=120)
        self.message_id = message_id

    @discord.ui.button(label="取り消す", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: RecruitBot = interaction.client
        rec = bot.store.get(self.message_id)
        if rec is None or rec.cancelled:
            await interaction.response.edit_message(content="この募集はすでに取り消されています。", view=None)
            return
        await interaction.response.edit_message(content="取り消し中…", view=None)
        rec.status = STATUS_CANCELLED
        await bot.save_and_refresh(rec)
        await bot.notify(rec, f"🗑️ 募集「**{rec.title}**」は取り消されました。")
        await interaction.edit_original_response(content="募集を取り消しました。")
        self.stop()

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def abort(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="取り消しを中止しました。", view=None)
        self.stop()
