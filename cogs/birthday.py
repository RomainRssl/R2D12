import json
import os
import io
import csv
import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

BIRTHDAY_FILE = "data/birthdays.json"

DEFAULT_MESSAGE = "Joyeux anniversaire {mention} ! Toute l'équipe de **{server}** te souhaite une merveilleuse journée !"

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
    return data.setdefault(str(guild_id), {
        "channel_id": None,
        "message": DEFAULT_MESSAGE,
        "dm_enabled": True,
        "members": {},
    })


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
    try:
        next_bday = datetime.date(today.year, month, day)
    except ValueError:
        next_bday = datetime.date(today.year, month, 28)
    if next_bday < today:
        try:
            next_bday = datetime.date(today.year + 1, month, day)
        except ValueError:
            next_bday = datetime.date(today.year + 1, month, 28)
    return (next_bday - today).days


def register_birthday(data: dict, guild_id: int, user_id: int, jour: int, mois: int):
    guild = get_guild(data, guild_id)
    guild["members"][str(user_id)] = {"day": jour, "month": mois}


# ── Modal d'enregistrement (utilisé par le bouton DM et la commande) ──────────

class BirthdayModal(discord.ui.Modal, title="🎂 Enregistrer votre anniversaire"):
    jour = discord.ui.TextInput(
        label="Jour de naissance",
        placeholder="Ex: 25",
        min_length=1,
        max_length=2,
    )
    mois = discord.ui.TextInput(
        label="Mois de naissance (numéro)",
        placeholder="Ex: 12 (pour décembre)",
        min_length=1,
        max_length=2,
    )

    def __init__(self, guild_id: int, guild_name: str):
        super().__init__()
        self.guild_id = guild_id
        self.guild_name = guild_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            j = int(self.jour.value.strip())
            m = int(self.mois.value.strip())
            datetime.date(2000, m, j)
        except (ValueError, TypeError):
            await interaction.response.send_message(
                f"Date invalide (`{self.jour.value}/{self.mois.value}`). Vérifiez le jour et le mois.",
                ephemeral=True,
            )
            return

        data = load_data()
        register_birthday(data, self.guild_id, interaction.user.id, j, m)
        save_data(data)

        jours = days_until_birthday(j, m)
        label = "aujourd'hui !" if jours == 0 else f"dans **{jours} jour(s)**"
        await interaction.response.send_message(
            f"🎂 Anniversaire enregistré : **{j} {MONTHS_FR[m]}** — {label}",
            ephemeral=True,
        )


# ── Vue pour le bouton dans le MP de bienvenue ────────────────────────────────

class BirthdayDMView(discord.ui.View):
    """Bouton envoyé en DM à l'arrivée pour enregistrer son anniversaire."""

    def __init__(self, guild_id: int, guild_name: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.guild_name = guild_name

    @discord.ui.button(
        label="🎂 Enregistrer mon anniversaire",
        style=discord.ButtonStyle.primary,
        custom_id="birthday:dm_register",
    )
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal(self.guild_id, self.guild_name))


# ── Groupe de commandes ───────────────────────────────────────────────────────


class Birthday(commands.Cog):
    """Souhaite automatiquement l'anniversaire des membres."""

    birthday_group = app_commands.Group(
        name="anniversaire",
        description="Gestion des anniversaires des membres",
    )

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
            for user_id, bday in config.get("members", {}).items():
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

    # ── Event : MP automatique à l'arrivée ───────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        data = load_data()
        config = get_guild(data, member.guild.id)

        if not config.get("dm_enabled", True):
            return

        embed = discord.Embed(
            title=f"Bienvenue sur {member.guild.name} !",
            description=(
                f"Bonjour {member.display_name} !\n\n"
                f"Pour que le serveur puisse vous souhaiter votre anniversaire, "
                f"cliquez sur le bouton ci-dessous pour enregistrer votre date de naissance.\n\n"
                f"_Cette information reste privée et n'est utilisée que pour les souhaits d'anniversaire._"
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        embed.set_footer(text="Vous pouvez aussi utiliser /anniversaire enregistrer sur le serveur.")

        try:
            await member.send(
                embed=embed,
                view=BirthdayDMView(member.guild.id, member.guild.name),
            )
        except discord.Forbidden:
            pass  # DMs fermés — on ne peut rien faire

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
        try:
            datetime.date(2000, mois, jour)
        except ValueError:
            await interaction.response.send_message(
                f"La date **{jour}/{mois}** n'est pas valide.", ephemeral=True
            )
            return

        data = load_data()
        register_birthday(data, interaction.guild_id, interaction.user.id, jour, mois)
        save_data(data)

        jours_restants = days_until_birthday(jour, mois)
        msg = (
            f"🎂 Anniversaire enregistré : **{jour} {MONTHS_FR[mois]}**.\n"
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

        upcoming = []
        for user_id, bday in members_data.items():
            member = interaction.guild.get_member(int(user_id))
            if not member:
                continue
            remaining = days_until_birthday(bday["day"], bday["month"])
            upcoming.append((remaining, bday["day"], bday["month"], member))

        upcoming.sort(key=lambda x: x[0])

        embed = discord.Embed(title="Prochains anniversaires", color=discord.Color.gold())
        for remaining, day, month, member in upcoming[:15]:
            if remaining == 0:
                label = "Aujourd'hui ! 🎉"
            elif remaining == 1:
                label = "Demain !"
            else:
                label = f"Dans {remaining} jours"
            embed.add_field(
                name=member.display_name,
                value=f"{day} {MONTHS_FR[month]} — {label}",
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    # ── Commandes admin ───────────────────────────────────────────────────────

    @birthday_group.command(name="configurer", description="Définir le salon et le message d'anniversaire")
    @app_commands.describe(
        salon="Salon où publier les messages d'anniversaire",
        message="Message d'anniversaire. Variables : {mention} {name} {username} {server}",
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
        embed.add_field(name="MP automatique", value="Activé" if guild.get("dm_enabled", True) else "Désactivé")
        embed.add_field(name="Variables", value="`{mention}` `{name}` `{username}` `{server}`", inline=False)
        embed.add_field(name="Message", value=message[:500], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @birthday_group.command(name="mp-activer", description="Activer le MP automatique d'enregistrement à l'arrivée")
    @app_commands.default_permissions(manage_guild=True)
    async def birthday_dm_enable(self, interaction: discord.Interaction):
        data = load_data()
        get_guild(data, interaction.guild_id)["dm_enabled"] = True
        save_data(data)
        await interaction.response.send_message(
            "✅ MP automatique activé — les nouveaux membres recevront un message pour enregistrer leur anniversaire.",
            ephemeral=True,
        )

    @birthday_group.command(name="mp-desactiver", description="Désactiver le MP automatique à l'arrivée")
    @app_commands.default_permissions(manage_guild=True)
    async def birthday_dm_disable(self, interaction: discord.Interaction):
        data = load_data()
        get_guild(data, interaction.guild_id)["dm_enabled"] = False
        save_data(data)
        await interaction.response.send_message(
            "❌ MP automatique désactivé.",
            ephemeral=True,
        )

    @birthday_group.command(name="importer", description="Importer des anniversaires en masse depuis un fichier CSV")
    @app_commands.describe(
        fichier="Fichier CSV avec colonnes : user_id,jour,mois (une ligne par membre)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def birthday_import(self, interaction: discord.Interaction, fichier: discord.Attachment):
        if not fichier.filename.endswith(".csv"):
            await interaction.response.send_message("Le fichier doit être au format `.csv`.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            raw = await fichier.read()
            content = raw.decode("utf-8-sig")  # gère le BOM Excel
        except Exception:
            await interaction.followup.send("Impossible de lire le fichier.", ephemeral=True)
            return

        reader = csv.DictReader(io.StringIO(content))
        # Normaliser les noms de colonnes (minuscules, sans espaces)
        fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]

        if not all(col in fieldnames for col in ["user_id", "jour", "mois"]):
            await interaction.followup.send(
                "Format CSV invalide. Colonnes attendues : `user_id`, `jour`, `mois`\n"
                "Exemple :\n```\nuser_id,jour,mois\n123456789,25,12\n987654321,14,2\n```",
                ephemeral=True,
            )
            return

        data = load_data()
        success, errors = [], []

        for i, row in enumerate(reader, start=2):
            # Normaliser les clés de la ligne
            row = {k.strip().lower(): v.strip() for k, v in row.items()}
            uid_raw = row.get("user_id", "").strip()
            jour_raw = row.get("jour", "").strip()
            mois_raw = row.get("mois", "").strip()

            # Résoudre l'ID (mention ou numérique)
            import re
            mention_match = re.search(r"<@!?(\d+)>", uid_raw)
            uid_str = mention_match.group(1) if mention_match else uid_raw

            if not uid_str.isdigit():
                errors.append(f"Ligne {i} : `{uid_raw}` n'est pas un ID valide")
                continue

            try:
                j, m = int(jour_raw), int(mois_raw)
                datetime.date(2000, m, j)
            except (ValueError, TypeError):
                errors.append(f"Ligne {i} : date invalide ({jour_raw}/{mois_raw})")
                continue

            register_birthday(data, interaction.guild_id, int(uid_str), j, m)
            member = interaction.guild.get_member(int(uid_str))
            name = member.display_name if member else f"ID {uid_str}"
            success.append(f"{name} — {j} {MONTHS_FR[m]}")

        if success:
            save_data(data)

        embed = discord.Embed(title="Import d'anniversaires", color=discord.Color.gold())
        embed.add_field(
            name=f"✅ Importés ({len(success)})",
            value="\n".join(success[:20]) + ("..." if len(success) > 20 else "") or "Aucun",
            inline=False,
        )
        if errors:
            embed.add_field(
                name=f"⚠️ Erreurs ({len(errors)})",
                value="\n".join(errors[:10]) + ("..." if len(errors) > 10 else ""),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

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
        embed = discord.Embed(title="Anniversaire !", description=text, color=discord.Color.gold())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="[TEST]")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @birthday_group.command(name="tester-mp", description="Simuler le MP de bienvenue d'anniversaire")
    @app_commands.default_permissions(manage_guild=True)
    async def birthday_test_dm(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"Bienvenue sur {interaction.guild.name} !",
            description=(
                f"Bonjour {interaction.user.display_name} !\n\n"
                "Pour que le serveur puisse vous souhaiter votre anniversaire, "
                "cliquez sur le bouton ci-dessous pour enregistrer votre date de naissance.\n\n"
                "_Cette information reste privée et n'est utilisée que pour les souhaits d'anniversaire._"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="[TEST] Vous pouvez aussi utiliser /anniversaire enregistrer sur le serveur.")
        try:
            await interaction.user.send(
                embed=embed,
                view=BirthdayDMView(interaction.guild_id, interaction.guild.name),
            )
            await interaction.response.send_message("MP de test envoyé dans vos messages privés.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Impossible d'envoyer le MP (vos DMs sont fermés).", ephemeral=True
            )

    @birthday_group.command(name="statut", description="Voir la configuration des anniversaires")
    async def birthday_status(self, interaction: discord.Interaction):
        data = load_data()
        guild = get_guild(data, interaction.guild_id)
        channel = interaction.guild.get_channel(guild.get("channel_id") or 0)
        nb = len(guild.get("members", {}))
        embed = discord.Embed(title="Configuration anniversaires", color=discord.Color.gold())
        embed.add_field(name="Salon", value=channel.mention if channel else "`non configuré`")
        embed.add_field(name="Heure d'envoi", value="08:00 UTC")
        embed.add_field(name="Membres inscrits", value=str(nb))
        embed.add_field(name="MP automatique", value="✅ Activé" if guild.get("dm_enabled", True) else "❌ Désactivé")
        embed.add_field(name="Message", value=guild.get("message", DEFAULT_MESSAGE)[:300], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthday(bot))
