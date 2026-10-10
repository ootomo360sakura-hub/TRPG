"""募集の作成・編集・取消に使うフォーム(モーダル)とボタン。"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from render import (
    DATE_FORMAT_HINT,
    DAY,
    WEEK,
    INTEREST_EMOJI,
    JOIN_EMOJI,
    TZ,
    build_embed,
    format_input_datetime,
    parse_datetime,
)
from store import EXTRA_FIELDS, STATUS_CANCELLED, Recruitment

if TYPE_CHECKING:
    from bot import RecruitBot

GM_MENU_ID = "recruit:gm_menu"


def reset_reminder_flags(rec: Recruitment) -> None:
    """開催日時から見て、すでに過ぎているリマインドは「送信済み」扱いにする。"""
    start = datetime.fromtimestamp(rec.start_at, TZ)
    now = datetime.now(TZ)
    rec.week_sent = now >= start - WEEK
    rec.day_sent = now >= start - DAY


# ---------------------------------------------------------------- フォーム


class BasicModal(discord.ui.Modal):
    """必須の基本項目(タイトル・日時・定員)+募集内容。作成と編集で共用。"""

    def __init__(self, rec: Recruitment | None = None) -> None:
        super().__init__(title="募集内容の編集" if rec else "TRPG募集を作成", timeout=900)
        self.rec = rec
        self.title_input = discord.ui.TextInput(
            label="タイトル(シナリオ名・卓名)", max_length=100, default=rec.title if rec else None
        )
        self.date_input = discord.ui.TextInput(
            label="開催日時",
            placeholder=DATE_FORMAT_HINT,
            max_length=40,
            default=format_input_datetime(rec.start_at) if rec else None,
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
        for item in (self.title_input, self.date_input, self.capacity_input, self.details_input):
            self.add_item(item)

    def parse(self) -> tuple[str, int, int, str]:
        start = parse_datetime(self.date_input.value)
        cap_text = self.capacity_input.value.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if not cap_text.isdigit() or not 1 <= int(cap_text) <= 30:
            raise ValueError("定員は1〜30の数字で入力してください。")
        return self.title_input.value.strip(), int(start.timestamp()), int(cap_text), self.details_input.value

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            title, start_at, capacity, details = self.parse()
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return

        if self.rec is None:
            rec = Recruitment(
                message_id=0,
                channel_id=interaction.channel_id,
                guild_id=interaction.guild_id,
                gm_id=interaction.user.id,
                title=title,
                start_at=start_at,
                capacity=capacity,
                details=details,
            )
            view = DraftView(rec)
            await interaction.response.send_message(
                content=view.guide_text(), embed=build_embed(rec), view=view, ephemeral=True
            )
            return

        bot: RecruitBot = interaction.client
        rec = bot.store.get(self.rec.message_id)
        if rec is None or rec.cancelled:
            await interaction.response.send_message("この募集はもう編集できません。", ephemeral=True)
            return
        date_changed = rec.start_at != start_at
        rec.title, rec.start_at, rec.capacity, rec.details = title, start_at, capacity, details
        if date_changed:
            reset_reminder_flags(rec)
        await interaction.response.defer(ephemeral=True)
        await bot.save_and_refresh(rec)
        await interaction.followup.send("✅ 募集内容を更新しました。", ephemeral=True)


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
            await interaction.response.send_message("⚠️ 開催日時が過ぎています。作り直してください。", ephemeral=True)
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
