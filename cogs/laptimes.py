import json
import os
import re
import datetime
import discord
from discord import app_commands
from discord.ext import commands

LAPTIMES_FILE = "data/laptimes.json"


def load_data() -> dict:
    if not os.path.exists(LAPTIMES_FILE):
        return {}
    with open(LAPTIMES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(LAPTIMES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_time(time_str: str) -> int | None:
    """Convertit mm:ss.mmm ou ss.mmm en millisecondes. Retourne None si invalide."""
    time_str = time_str.strip().replace(",", ".")
    match = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2})\.(\d{1,3})", time_str)
    if not match:
        return None
    minutes = int(match.group(1) or 0)
    seconds = int(match.group(2))
    millis_str = match.group(3).ljust(3, "0")[:3]
    millis = int(millis_str)
    if seconds >= 60:
        return None
    return minutes * 60_000 + seconds * 1_000 + millis


def format_time(ms: int) -> str:
    """Convertit des millisecondes en mm:ss.mmm."""
    minutes = ms // 60_000
    remaining = ms % 60_000
    seconds = remaining // 1_000
    millis = remaining % 1_000
    if minutes > 0:
        return f"{minutes}:{seconds:02d}.{millis:03d}"
    return f"{seconds}.{millis:03d}"


def make_key(voiture: str, piste: str) -> str:
    return f"{voiture.lower().strip()}|{piste.lower().strip()}"


class LapTimes(commands.Cog):
    """Leaderboard de temps au tour par voiture et par piste."""

    temps_group = app_commands.Group(name="temps", description="Leaderboard des meilleurs temps au tour")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @temps_group.command(name="enregistrer", description="Enregistrer votre meilleur temps au tour")
    @app_commands.describe(
        voiture="Nom de la voiture (ex: Ferrari 488 GT3)",
        piste="Nom de la piste (ex: Spa-Francorchamps)",
        temps="Temps au format mm:ss.mmm ou ss.mmm (ex: 2:17.543)",
        simulateur="Simulateur utilisé (ex: Assetto Corsa, iRacing...)",
    )
    async def laptime_set(
        self, interaction: discord.Interaction,
        voiture: str, piste: str, temps: str,
        simulateur: str = None,
    ):
        ms = parse_time(temps)
        if ms is None:
            await interaction.response.send_message(
                "Format de temps invalide. Utilisez `mm:ss.mmm` (ex: `2:17.543`) ou `ss.mmm` (ex: `58.321`).",
                ephemeral=True,
            )
            return

        data = load_data()
        guild_key = str(interaction.guild_id)
        key = make_key(voiture, piste)
        entries = data.setdefault(guild_key, {}).setdefault(key, {
            "voiture": voiture.strip(),
            "piste": piste.strip(),
            "times": [],
        })

        user_key = str(interaction.user.id)
        # Garde uniquement le meilleur temps par utilisateur
        entries["times"] = [t for t in entries["times"] if t["user_id"] != user_key]
        entries["times"].append({
            "user_id": user_key,
            "ms": ms,
            "date": datetime.datetime.utcnow().strftime("%d/%m/%Y"),
            "simulateur": simulateur or "Non précisé",
        })
        # Trier par temps croissant
        entries["times"].sort(key=lambda t: t["ms"])
        save_data(data)

        position = next(i + 1 for i, t in enumerate(entries["times"]) if t["user_id"] == user_key)
        embed = discord.Embed(
            title="Temps enregistré ✅",
            color=discord.Color.green() if position == 1 else discord.Color.blurple(),
        )
        embed.add_field(name="Voiture", value=voiture.strip(), inline=True)
        embed.add_field(name="Piste", value=piste.strip(), inline=True)
        embed.add_field(name="Temps", value=f"**{format_time(ms)}**", inline=True)
        embed.add_field(name="Position", value=f"**#{position}** sur {len(entries['times'])} pilotes", inline=True)
        if simulateur:
            embed.add_field(name="Simulateur", value=simulateur, inline=True)
        if position == 1:
            embed.set_footer(text="🏆 Nouveau record du serveur !")
        await interaction.response.send_message(embed=embed)

    @temps_group.command(name="classement", description="Voir le classement des meilleurs temps")
    @app_commands.describe(
        voiture="Nom de la voiture",
        piste="Nom de la piste",
    )
    async def laptime_board(self, interaction: discord.Interaction, voiture: str, piste: str):
        data = load_data()
        key = make_key(voiture, piste)
        entries = data.get(str(interaction.guild_id), {}).get(key)

        if not entries or not entries.get("times"):
            await interaction.response.send_message(
                f"Aucun temps enregistré pour **{voiture.strip()}** sur **{piste.strip()}**.", ephemeral=True
            )
            return

        medals = ["🥇", "🥈", "🥉"]
        embed = discord.Embed(
            title=f"🏆 Classement — {entries['voiture']}",
            description=f"📍 {entries['piste']}",
            color=discord.Color.gold(),
        )
        for i, entry in enumerate(entries["times"][:15]):
            member = interaction.guild.get_member(int(entry["user_id"]))
            name = member.display_name if member else f"ID {entry['user_id']}"
            prefix = medals[i] if i < 3 else f"`#{i+1}`"
            gap = ""
            if i > 0:
                diff = entry["ms"] - entries["times"][0]["ms"]
                gap = f" (+{format_time(diff)})"
            embed.add_field(
                name=f"{prefix} {name}",
                value=f"**{format_time(entry['ms'])}**{gap} • {entry['simulateur']} • {entry['date']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @temps_group.command(name="personnel", description="Voir tous vos meilleurs temps enregistrés")
    @app_commands.describe(membre="Le membre dont voir les temps (vous par défaut)")
    async def laptime_personal(self, interaction: discord.Interaction, membre: discord.Member = None):
        membre = membre or interaction.user
        data = load_data()
        guild_data = data.get(str(interaction.guild_id), {})
        user_key = str(membre.id)

        results = []
        for key, entries in guild_data.items():
            for i, t in enumerate(entries.get("times", [])):
                if t["user_id"] == user_key:
                    results.append((entries["voiture"], entries["piste"], t["ms"], i + 1, len(entries["times"]), t["date"]))

        if not results:
            await interaction.response.send_message(f"{membre.mention} n'a aucun temps enregistré.", ephemeral=True)
            return

        embed = discord.Embed(title=f"Temps de {membre.display_name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=membre.display_avatar.url)
        for voiture, piste, ms, pos, total, date in sorted(results, key=lambda x: x[0]):
            embed.add_field(
                name=f"{voiture} — {piste}",
                value=f"**{format_time(ms)}** • #{pos}/{total} • {date}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @temps_group.command(name="supprimer", description="Supprimer votre temps sur une combinaison voiture/piste")
    @app_commands.describe(voiture="Nom de la voiture", piste="Nom de la piste")
    async def laptime_delete(self, interaction: discord.Interaction, voiture: str, piste: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        key = make_key(voiture, piste)
        entries = data.get(guild_key, {}).get(key)

        if not entries:
            await interaction.response.send_message("Aucun temps trouvé pour cette combinaison.", ephemeral=True)
            return

        user_key = str(interaction.user.id)
        before = len(entries["times"])
        entries["times"] = [t for t in entries["times"] if t["user_id"] != user_key]
        if len(entries["times"]) == before:
            await interaction.response.send_message("Vous n'avez pas de temps enregistré pour cette combinaison.", ephemeral=True)
            return

        save_data(data)
        await interaction.response.send_message(
            f"Votre temps sur **{voiture.strip()}** / **{piste.strip()}** a été supprimé.", ephemeral=True
        )

    # ── Autocomplete ──────────────────────────────────────────────────────────

    @laptime_board.autocomplete("voiture")
    @laptime_delete.autocomplete("voiture")
    async def autocomplete_car(self, interaction: discord.Interaction, current: str):
        data = load_data()
        seen = set()
        choices = []
        for entries in data.get(str(interaction.guild_id), {}).values():
            v = entries.get("voiture", "")
            if v and v not in seen and current.lower() in v.lower():
                seen.add(v)
                choices.append(app_commands.Choice(name=v, value=v))
        return choices[:25]

    @laptime_board.autocomplete("piste")
    @laptime_delete.autocomplete("piste")
    async def autocomplete_track(self, interaction: discord.Interaction, current: str):
        data = load_data()
        seen = set()
        choices = []
        for entries in data.get(str(interaction.guild_id), {}).values():
            p = entries.get("piste", "")
            if p and p not in seen and current.lower() in p.lower():
                seen.add(p)
                choices.append(app_commands.Choice(name=p, value=p))
        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(LapTimes(bot))
