import discord
from discord.ext import commands
from discord import app_commands
import random
import sqlite3
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

REROLL_COOLDOWN_DAYS = int(os.getenv("REROLL_COOLDOWN_DAYS", "7"))
DB_PATH = "/data/bot_data.db"

# ─── Погонялы ─────────────────────────────────────────────────────────────────
NICKNAMES: dict[str, str] = {
    "говно":     "\u2623\ufe0f СУПЕР СПОСОБНОСТЬ: ЗАРАЖАЕТ ГОВНОМ ВСЕХ КТО ПИШЕТ ДО И ПОСЛЕ НЕГО В ЧАТЕ",
    "Обоссаный": "\U0001f4a6 ВСЕ В ЧАТЕ НА НЕГО ССУТ",
    "водолаз":   "\U0001f4a8 ОБЯЗАН РТОМ ЛОВИТЬ ПЕРДЁЖ",
    "терпила":   "\U0001f44a ЕГО МОЖНО ОСКОРБЛЯТЬ, А ОН БУДЕТ ТЕРПЕТЬ",
}

_all_nicknames = list(NICKNAMES.keys())  # равный шанс на каждое


def _roll_nickname() -> str:
    return random.choice(_all_nicknames)


def _build_announcement(display_name: str, nickname: str, reroll: bool = False) -> str:
    verb = "ПЕРЕБРОСИЛ И ПОЛУЧАЕТ" if reroll else "ПОЛУЧАЕТ"
    lines = [
        f"\U0001f6a8 ВСЕМ ВНИМАНИЕ. ПОЛЬЗОВАТЕЛЬ С НИКОМ **{display_name}** {verb} ПОГОНЯЛО **{nickname}**"
    ]
    extra = NICKNAMES.get(nickname)
    if extra:
        lines.append(extra)
    return "\n".join(lines)


# ─── База данных ──────────────────────────────────────────────────────────────
def db_nickname_init() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_nicknames (
                user_id     INTEGER PRIMARY KEY,
                nickname    TEXT    NOT NULL,
                assigned_at TEXT    NOT NULL
            )
        """)


def db_get_nickname(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT nickname, assigned_at FROM user_nicknames WHERE user_id = ?",
            (user_id,),
        ).fetchone()  # (nickname, assigned_at) | None


def db_set_nickname(user_id: int, nickname: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO user_nicknames (user_id, nickname, assigned_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE
                SET nickname    = excluded.nickname,
                    assigned_at = excluded.assigned_at
        """, (user_id, nickname, now))


# ─── Cog ──────────────────────────────────────────────────────────────────────
class NicknameCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db_nickname_init()

    async def _assign_and_announce(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reroll: bool = False,
    ) -> None:
        nickname = _roll_nickname()
        db_set_nickname(member.id, nickname)
        await interaction.response.send_message(
            _build_announcement(member.display_name, nickname, reroll=reroll)
        )

    # ── /погоняло ─────────────────────────────────────────────────────────────
    @app_commands.command(name="погоняло", description="Узнать своё погоняло (или чужое)")
    async def pogonyalo(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
    ) -> None:
        target = user or interaction.user
        if not isinstance(target, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return

        row = db_get_nickname(target.id)

        if row is None:
            await self._assign_and_announce(interaction, target)
            return

        nickname, assigned_at = row
        days_ago = (datetime.now(timezone.utc) - datetime.fromisoformat(assigned_at)).days
        extra = NICKNAMES.get(nickname)
        extra_line = f"\n{extra}" if extra else ""

        await interaction.response.send_message(
            f"Погоняло **{target.display_name}**: **{nickname}**{extra_line}\n"
            f"*Выдано {days_ago} дн. назад*"
        )

    # ── /перебросить ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="перебросить",
        description=f"Перебросить своё погоняло (раз в {REROLL_COOLDOWN_DAYS} дней)",
    )
    async def reroll(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Только на сервере.", ephemeral=True)
            return

        row = db_get_nickname(interaction.user.id)

        if row is None:
            await self._assign_and_announce(interaction, interaction.user)
            return

        _, assigned_at = row
        elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(assigned_at)

        if elapsed.total_seconds() < REROLL_COOLDOWN_DAYS * 86400:
            remaining = REROLL_COOLDOWN_DAYS - elapsed.days
            await interaction.response.send_message(
                f"Ты уже кидал бля. Следующий бросок через **{remaining} дн.**",
                ephemeral=True,
            )
            return

        await self._assign_and_announce(interaction, interaction.user, reroll=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NicknameCog(bot))
