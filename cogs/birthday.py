import json
import os
import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

BIRTHDAY_FILE = "data/birthdays.json"

DEFAULT_MESSAGE = "Joyeux anniversaire {mention} ! Toute l'équipe de **{server}** te souhaite une merveilleuse journée !"

# Heure d'envoi des messages d'anniversaire (UTC)
BIRTHDAY_HOUR = datetime.time(hour=8, minute=0, tzinfo=datetime.timezone.utc)

MONTHS_FR = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}


# ── Persistance ───────────────────────────────────────────────────────────────

def load_data() -> dict:
    if not os.path.exists(BIRTHDAY_FILE):
        return {}
    with open(BIRTHDAY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(BIRTHDAY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_guild(data: dict, guild_id: int) -> dict:
    return data.setdefault(str(guild_id), {"channel_id": None, "message": DEFAULT_MESSAGE, "members": {}})


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_message(message: str, member: discord.Member) -> str:
    return message.format(
        mention=member.mention,
        name=member.display_name,
        username=member.name,
        server=member.guild.name,
    )


def days_until_birthday(day: int, month: int) -> int:
    today = datetime.date.today()
    next_bday = datetime.date(today.year, month, day)
    if next_bday < today:
        next_bday = datetime.date(today.year + 1, month, day)
    return (next_bday - today).days


def is_birthday_today(day: int, month: int) -> bool:
    today = datetime.date.today()
    return today.day == day and today.month == month


# ── Groupe de commandes ───────────────────────────────────────────────────────

birthday_group = app_commands.Group(
    name="anniversaire",
    description="Gestion des anniversaires des membres",
)


class Birthday(commands.Cog):
    """Souhaite automatiquement l'anniversaire des membres."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()

    # ── Tâche planifiée ───────────────────────────────────────────────────────

    @tasks.loop(time=BIRTHDAY_HOUR)
    async def check_birthdays(self):
        data = load_data()
        today = datetime.date.today()

        for guild_id, config in data.items():
            channel_id = config.get("channel_id")
            if not channel_id:
                continue

            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                continue

            message_template = config.get("message", DEFAULT_MESSAGE)
            members_data = config.get("members", {})

            for user_id, bday in members_data.items():
                if bday["day"] == today.day and bday["month"] == today.month:
                    member = guild.get_member(int(user_id))
                    if not member:
                        continue

                    text = format_message(message_template, member)
                    embed = discord.Embed(
                        title="Anniversaire !",
                        description=text,
                        color=discord.Color.gold(),
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=f"{today.day} {MONTHS_FR[today.month]}")
                    await channel.send(embed=embed)

    @check_birthdays.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── Commandes membres ─────────────────────────────────────────────────────

    @birthday_group.command(name="enregistrer", description="Enregistrer votre date d'anniversaire")
    @app_commands.describe(
        jour="Jour de votre anniversaire (1-31)",
        mois="Mois de votre anniversaire (1-12)",
    )
    async def birthday_set(
        self,
        interaction: discord.Interaction,
        jour: app_commands.Range[int, 1, 31],
        mois: app_commands.Range[int, 1, 12],
    ):
        # Validation de la date
        try:
            datetime.date(2000, mois, jour)
        except ValueError:
            await interaction.response.send_message(
                f"La date **{jour}/{mois}** n'est pas valide.", ephemeral=True
            )
            return

        data = load_data()
        guild = get_guild(data, interaction.guild_id)
        guild["members"][str(interaction.user.id)] = {"day": jour, "month": mois}
        save_data(data)

        jours_restants = days_until_birthday(jour, mois)
        msg = (
            f"Anniversaire enregistré : **{jour} {MONTHS_FR[mois]}**.\n"
            f"{'Votre anniversaire est **aujourd\'hui** !' if jours_restants == 0 else f'Plus que **{jours_restants} jour(s)** !'}"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @birthday_group.command(name="supprimer", description="Supprimer votre date d'anniversaire")
    async def birthday_remove(self, interaction: discord.Interaction):
        data = load_data()
        guild = get_guild(data, interaction.guild_id)
        user_key = str(interaction.user.id)

        if user_key not in guild["members"]:
            await interaction.response.send_message("Vous n'avez pas enregistré votre anniversaire.", ephemeral=True)
            return

        del guild["members"][user_key]
        save_data(data)
        await interaction.response.send_message("Votre anniversaire a été supprimé.", ephemeral=True)

    @birthday_group.command(name="prochains", description="Voir les prochains anniversaires du serveur")
    async def birthday_upcoming(self, interaction: discord.Interaction):
        data = load_data()
        guild = get_guild(data, interaction.guild_id)
        members_data = guild.get("members", {})

        if not members_data:
            await interaction.response.send_message("Aucun anniversaire enregistré sur ce serveur.", ephemeral=True)
            return

        # Trier par jours restants
        upcoming = []
        for user_id, bday in members_data.items():
            member = interaction.guild.get_member(int(user_id))
            if not member:
                continue
            remaining = days_until_birthday(bday["day"], bday["month"])
            upcoming.append((remaining, bday["day"], bday["month"], member))

        upcoming.sort(key=lambda x: x[0])

        embed = discord.Embed(
            title="Prochains anniversaires",
            color=discord.Color.gold(),
        )
        for remaining, day, month, member in upcoming[:15]:
            if remaining == 0:
                label = "Aujourd'hui !"
            elif remaining == 1:
                label = "Demain !"
            else:
                label = f"Dans {remaining} jours"
            embed.add_field(
                name=f"{member.display_name}",
                value=f"{day} {MONTHS_FR[month]} — {label}",
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    # ── Commandes admin ───────────────────────────────────────────────────────

    @birthday_group.command(name="configurer", description="Définir le salon et le message d'anniversaire")
    @app_commands.describe(
        salon="Salon où publier les messages d'anniversaire",
        message=(
            "Message d'anniversaire. "
            "Variables : {mention} {name} {username} {server}"
        ),
    )
    @app_commands.default_permissions(manage_guild=True)
    async def birthday_config(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel,
        message: str = DEFAULT_MESSAGE,
    ):
        data = load_data()
        guild = get_guild(data, interaction.guild_id)
        guild["channel_id"] = salon.id
        guild["message"] = message
        save_data(data)

        embed = discord.Embed(title="Anniversaires configurés", color=discord.Color.gold())
        embed.add_field(name="Salon", value=salon.mention)
        embed.add_field(name="Heure d'envoi", value="08:00 UTC")
        embed.add_field(
            name="Variables disponibles",
            value="`{mention}` `{name}` `{username}` `{server}`",
            inline=False,
        )
        embed.add_field(name="Message", value=message[:500], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @birthday_group.command(name="tester", description="Simuler un message d'anniversaire pour vous-même")
    async def birthday_test(self, interaction: discord.Interaction):
        data = load_data()
        guild = get_guild(data, interaction.guild_id)

        if not guild.get("channel_id"):
            await interaction.response.send_message(
                "Aucun salon configuré. Utilisez `/anniversaire configurer` d'abord.", ephemeral=True
            )
            return

        message_template = guild.get("message", DEFAULT_MESSAGE)
        text = format_message(message_template, interaction.user)

        embed = discord.Embed(
            title="Anniversaire !",
            description=text,
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="[TEST]")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @birthday_group.command(name="statut", description="Voir la configuration des anniversaires")
    async def birthday_status(self, interaction: discord.Interaction):
        data = load_data()
        guild = get_guild(data, interaction.guild_id)

        channel = interaction.guild.get_channel(guild.get("channel_id") or 0)
        nb_membres = len(guild.get("members", {}))

        embed = discord.Embed(title="Configuration anniversaires", color=discord.Color.gold())
        embed.add_field(name="Salon", value=channel.mention if channel else "`non configuré`")
        embed.add_field(name="Heure d'envoi", value="08:00 UTC")
        embed.add_field(name="Membres inscrits", value=str(nb_membres))
        embed.add_field(name="Message", value=guild.get("message", DEFAULT_MESSAGE)[:300], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Birthday(bot)
    bot.tree.add_command(birthday_group)
    await bot.add_cog(cog)
