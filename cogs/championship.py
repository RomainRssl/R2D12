import json
import os
import discord
from discord import app_commands
from discord.ext import commands

CHAMP_FILE = "data/championships.json"

# Systèmes de points disponibles
POINTS_SYSTEMS = {
    "f1": [25, 18, 15, 12, 10, 8, 6, 4, 2, 1],
    "f2": [25, 18, 15, 12, 10, 8, 6, 4, 2, 1, 0, 0],
    "indycar": [50, 40, 35, 32, 30, 28, 26, 24, 22, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10],
    "simple": [10, 8, 6, 5, 4, 3, 2, 1],
    "égal": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
}


def load_data() -> dict:
    if not os.path.exists(CHAMP_FILE):
        return {}
    with open(CHAMP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(CHAMP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_standings(championship: dict, guild: discord.Guild) -> list[tuple]:
    """Retourne [(points, user_id, victoires, podiums)] trié par points décroissants."""
    points_table: dict[str, int] = {}
    victories: dict[str, int] = {}
    podiums: dict[str, int] = {}
    fl_bonus: dict[str, int] = {}
    system = POINTS_SYSTEMS.get(championship.get("points_system", "f1"), POINTS_SYSTEMS["f1"])

    for race in championship.get("races", []):
        results = race.get("results", [])
        for pos, entry in enumerate(results):
            uid = entry["user_id"]
            pts = system[pos] if pos < len(system) else 0
            # Bonus meilleur tour
            if entry.get("meilleur_tour") and pos < 10:
                pts += 1
                fl_bonus[uid] = fl_bonus.get(uid, 0) + 1
            points_table[uid] = points_table.get(uid, 0) + pts
            if pos == 0:
                victories[uid] = victories.get(uid, 0) + 1
            if pos < 3:
                podiums[uid] = podiums.get(uid, 0) + 1

        # Pénalités
        for pen in race.get("penalties", []):
            uid = pen["user_id"]
            points_table[uid] = points_table.get(uid, 0) - pen.get("points", 0)

    sorted_standings = sorted(points_table.items(), key=lambda x: x[1], reverse=True)
    return [(pts, uid, victories.get(uid, 0), podiums.get(uid, 0)) for pts, uid in [(v, k) for k, v in sorted_standings]]


class Championship(commands.Cog):
    """Championnats, résultats de courses, incidents et pénalités."""

    champ_group = app_commands.Group(name="championnat", description="Gestion des championnats et ligues de simracing")
    incident_group = app_commands.Group(name="incident", description="Gestion des incidents de course")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Gestion du championnat ────────────────────────────────────────────────

    @champ_group.command(name="creer", description="Créer un nouveau championnat")
    @app_commands.describe(
        nom="Nom du championnat",
        points_system="Système de points (f1, f2, indycar, simple, égal)",
        description="Description du championnat (optionnel)",
    )
    @app_commands.choices(points_system=[
        app_commands.Choice(name="F1 (25-18-15-12-10-8-6-4-2-1)", value="f1"),
        app_commands.Choice(name="F2 (25-18-15-12-10-8-6-4-2-1)", value="f2"),
        app_commands.Choice(name="IndyCar (50-40-35-32...)", value="indycar"),
        app_commands.Choice(name="Simple (10-8-6-5-4-3-2-1)", value="simple"),
        app_commands.Choice(name="Égal (1 point par finissant)", value="égal"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def champ_create(
        self, interaction: discord.Interaction,
        nom: str, points_system: str = "f1", description: str = None,
    ):
        data = load_data()
        guild_key = str(interaction.guild_id)
        champs = data.setdefault(guild_key, {})

        nom_key = nom.lower().strip()
        if nom_key in champs:
            await interaction.response.send_message(f"Un championnat **{nom}** existe déjà.", ephemeral=True)
            return

        champs[nom_key] = {
            "nom": nom.strip(),
            "points_system": points_system,
            "description": description or "",
            "races": [],
            "pilotes": [],
        }
        save_data(data)

        system = POINTS_SYSTEMS[points_system]
        embed = discord.Embed(title=f"🏆 Championnat créé : {nom}", color=discord.Color.gold())
        embed.add_field(name="Système de points", value=" — ".join(str(p) for p in system[:10]))
        if description:
            embed.add_field(name="Description", value=description, inline=False)
        await interaction.response.send_message(embed=embed)

    @champ_group.command(name="classement", description="Voir le classement d'un championnat")
    @app_commands.describe(nom="Nom du championnat")
    async def champ_standings(self, interaction: discord.Interaction, nom: str):
        data = load_data()
        championship = data.get(str(interaction.guild_id), {}).get(nom.lower().strip())
        if not championship:
            await interaction.response.send_message(f"Championnat **{nom}** introuvable.", ephemeral=True)
            return

        standings = get_standings(championship, interaction.guild)
        if not standings:
            await interaction.response.send_message(f"Aucun résultat enregistré pour **{championship['nom']}**.", ephemeral=True)
            return

        medals = ["🥇", "🥈", "🥉"]
        embed = discord.Embed(
            title=f"🏆 {championship['nom']} — Classement",
            description=championship.get("description") or "",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name=f"Système : {championship['points_system'].upper()}",
            value=f"{len(championship['races'])} manche(s) disputée(s)",
            inline=False,
        )

        for i, (pts, uid, wins, pods) in enumerate(standings[:20]):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"ID {uid}"
            prefix = medals[i] if i < 3 else f"`#{i+1}`"
            gap = ""
            if i > 0 and standings:
                diff = standings[0][0] - pts
                gap = f" (-{diff} pts)" if diff > 0 else ""
            embed.add_field(
                name=f"{prefix} {name}",
                value=f"**{pts} pts**{gap} • {wins} victoire(s) • {pods} podium(s)",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @champ_group.command(name="resultat", description="Enregistrer les résultats d'une course")
    @app_commands.describe(
        nom="Nom du championnat",
        manche="Nom ou numéro de la manche (ex: Manche 3 — Monza)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def champ_result(self, interaction: discord.Interaction, nom: str, manche: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        championship = data.get(guild_key, {}).get(nom.lower().strip())
        if not championship:
            await interaction.response.send_message(f"Championnat **{nom}** introuvable.", ephemeral=True)
            return
        await interaction.response.send_modal(RaceResultModal(guild_key, nom.lower().strip(), manche, data))

    @champ_group.command(name="liste", description="Voir tous les championnats du serveur")
    async def champ_list(self, interaction: discord.Interaction):
        data = load_data()
        champs = data.get(str(interaction.guild_id), {})
        if not champs:
            await interaction.response.send_message("Aucun championnat créé.", ephemeral=True)
            return
        embed = discord.Embed(title="Championnats du serveur", color=discord.Color.gold())
        for key, c in champs.items():
            embed.add_field(
                name=c["nom"],
                value=f"Système : {c['points_system'].upper()} • {len(c['races'])} manche(s)\n{c.get('description', '')[:80]}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @champ_group.command(name="calendrier", description="Voir les manches d'un championnat")
    @app_commands.describe(nom="Nom du championnat")
    async def champ_calendar(self, interaction: discord.Interaction, nom: str):
        data = load_data()
        championship = data.get(str(interaction.guild_id), {}).get(nom.lower().strip())
        if not championship:
            await interaction.response.send_message(f"Championnat **{nom}** introuvable.", ephemeral=True)
            return
        races = championship.get("races", [])
        if not races:
            await interaction.response.send_message(f"Aucune manche enregistrée pour **{championship['nom']}**.", ephemeral=True)
            return
        embed = discord.Embed(title=f"📅 {championship['nom']} — Calendrier", color=discord.Color.blurple())
        for i, race in enumerate(races, 1):
            winner_id = race["results"][0]["user_id"] if race.get("results") else None
            winner = interaction.guild.get_member(int(winner_id)) if winner_id else None
            embed.add_field(
                name=f"Manche {i} — {race['nom']}",
                value=f"{'✅ Vainqueur : ' + winner.display_name if winner else '⏳ Non disputée'}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @champ_group.command(name="supprimer", description="Supprimer un championnat")
    @app_commands.describe(nom="Nom du championnat à supprimer")
    @app_commands.default_permissions(manage_guild=True)
    async def champ_delete(self, interaction: discord.Interaction, nom: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        nom_key = nom.lower().strip()
        if nom_key not in data.get(guild_key, {}):
            await interaction.response.send_message(f"Championnat **{nom}** introuvable.", ephemeral=True)
            return
        del data[guild_key][nom_key]
        save_data(data)
        await interaction.response.send_message(f"Championnat **{nom}** supprimé.", ephemeral=True)

    # ── Incidents & Pénalités ─────────────────────────────────────────────────

    @incident_group.command(name="signaler", description="Signaler un incident de course")
    @app_commands.describe(
        pilote="Pilote impliqué",
        raison="Description de l'incident",
        championnat="Championnat concerné (optionnel)",
    )
    async def incident_report(
        self, interaction: discord.Interaction,
        pilote: discord.Member, raison: str,
        championnat: str = None,
    ):
        embed = discord.Embed(
            title="🚨 Incident signalé",
            color=discord.Color.red(),
        )
        embed.add_field(name="Pilote mis en cause", value=pilote.mention)
        embed.add_field(name="Signalé par", value=interaction.user.mention)
        embed.add_field(name="Raison", value=raison, inline=False)
        if championnat:
            embed.add_field(name="Championnat", value=championnat, inline=True)
        embed.set_footer(text="En attente de décision des stewards")
        await interaction.response.send_message(embed=embed)

    @incident_group.command(name="penalite", description="Appliquer une pénalité à un pilote")
    @app_commands.describe(
        pilote="Pilote sanctionné",
        type="Type de pénalité",
        raison="Raison de la pénalité",
        championnat="Championnat concerné",
        points_retires="Points à retirer au classement (optionnel)",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Avertissement", value="Avertissement"),
        app_commands.Choice(name="Drive-through", value="Drive-through"),
        app_commands.Choice(name="Stop & Go (10s)", value="Stop & Go 10s"),
        app_commands.Choice(name="Stop & Go (30s)", value="Stop & Go 30s"),
        app_commands.Choice(name="Pénalité de temps (5s)", value="Pénalité +5s"),
        app_commands.Choice(name="Pénalité de temps (10s)", value="Pénalité +10s"),
        app_commands.Choice(name="Disqualification", value="Disqualification"),
        app_commands.Choice(name="Exclusion de course", value="Exclusion"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def penalty_apply(
        self, interaction: discord.Interaction,
        pilote: discord.Member, type: str, raison: str,
        championnat: str = None,
        points_retires: app_commands.Range[int, 0, 50] = 0,
    ):
        # Enregistrer dans le championnat si précisé
        if championnat and points_retires > 0:
            data = load_data()
            guild_key = str(interaction.guild_id)
            champ = data.get(guild_key, {}).get(championnat.lower().strip())
            if champ and champ.get("races"):
                last_race = champ["races"][-1]
                last_race.setdefault("penalties", []).append({
                    "user_id": str(pilote.id),
                    "type": type,
                    "raison": raison,
                    "points": points_retires,
                })
                save_data(data)

        embed = discord.Embed(
            title="⚖️ Décision des Stewards",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Pilote", value=pilote.mention)
        embed.add_field(name="Sanction", value=f"**{type}**")
        embed.add_field(name="Raison", value=raison, inline=False)
        if championnat:
            embed.add_field(name="Championnat", value=championnat, inline=True)
        if points_retires > 0:
            embed.add_field(name="Points retirés", value=f"-{points_retires} pts", inline=True)
        embed.set_footer(text=f"Décision prise par {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

        # Notifier le pilote
        try:
            await pilote.send(
                f"Vous avez reçu une pénalité sur le serveur **{interaction.guild.name}** :\n"
                f"**{type}** — {raison}"
            )
        except discord.Forbidden:
            pass

    # ── Autocomplete ──────────────────────────────────────────────────────────

    @champ_standings.autocomplete("nom")
    @champ_result.autocomplete("nom")
    @champ_calendar.autocomplete("nom")
    @champ_delete.autocomplete("nom")
    @penalty_apply.autocomplete("championnat")
    async def autocomplete_champ(self, interaction: discord.Interaction, current: str):
        data = load_data()
        champs = data.get(str(interaction.guild_id), {})
        return [
            app_commands.Choice(name=v["nom"], value=v["nom"])
            for k, v in champs.items() if current.lower() in v["nom"].lower()
        ][:25]


class RaceResultModal(discord.ui.Modal):
    """Modal pour saisir les résultats d'une course (jusqu'à 10 pilotes)."""

    def __init__(self, guild_id: str, champ_key: str, race_name: str, data: dict):
        super().__init__(title=f"Résultats — {race_name[:30]}")
        self.guild_id = guild_id
        self.champ_key = champ_key
        self.race_name = race_name
        self.data = data

        self.resultats = discord.ui.TextInput(
            label="Résultats (1 mention @ou ID par ligne, P1 en 1er)",
            placeholder="@pilote1\n@pilote2\n@pilote3\n...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
        )
        self.meilleur_tour = discord.ui.TextInput(
            label="Meilleur tour (mention @ou ID, optionnel)",
            placeholder="@pilote ou vide",
            required=False,
            max_length=100,
        )
        self.add_item(self.resultats)
        self.add_item(self.meilleur_tour)

    async def on_submit(self, interaction: discord.Interaction):
        lines = [l.strip() for l in self.resultats.value.strip().splitlines() if l.strip()]
        results = []
        errors = []

        for i, line in enumerate(lines):
            # Chercher une mention (<@123>) ou un ID numérique
            uid = None
            mention_match = __import__("re").search(r"<@!?(\d+)>", line)
            if mention_match:
                uid = mention_match.group(1)
            elif line.isdigit():
                uid = line
            else:
                # Chercher par nom d'affichage
                member = discord.utils.find(
                    lambda m: m.display_name.lower() == line.lower() or m.name.lower() == line.lower(),
                    interaction.guild.members,
                )
                if member:
                    uid = str(member.id)

            if uid:
                results.append({"user_id": uid, "position": i + 1, "meilleur_tour": False})
            else:
                errors.append(f"Ligne {i+1} : `{line}` introuvable")

        # Meilleur tour
        fl_line = self.meilleur_tour.value.strip()
        if fl_line:
            import re
            fl_match = re.search(r"<@!?(\d+)>", fl_line)
            fl_uid = fl_match.group(1) if fl_match else (fl_line if fl_line.isdigit() else None)
            if fl_uid:
                for r in results:
                    if r["user_id"] == fl_uid:
                        r["meilleur_tour"] = True
                        break

        if not results:
            await interaction.response.send_message("Aucun pilote reconnu dans les résultats.", ephemeral=True)
            return

        data = self.data
        championship = data[self.guild_id][self.champ_key]
        championship.setdefault("races", []).append({
            "nom": self.race_name,
            "results": results,
            "penalties": [],
        })
        save_data(data)

        system = POINTS_SYSTEMS.get(championship.get("points_system", "f1"), POINTS_SYSTEMS["f1"])
        embed = discord.Embed(
            title=f"✅ Résultats enregistrés — {self.race_name}",
            color=discord.Color.green(),
        )
        embed.add_field(name="Championnat", value=championship["nom"])

        lines_out = []
        medals = ["🥇", "🥈", "🥉"]
        for i, r in enumerate(results[:10]):
            member = interaction.guild.get_member(int(r["user_id"]))
            name = member.display_name if member else f"ID {r['user_id']}"
            pts = system[i] if i < len(system) else 0
            fl = " 🟣 Meilleur tour (+1)" if r.get("meilleur_tour") and i < 10 else ""
            prefix = medals[i] if i < 3 else f"P{i+1}"
            lines_out.append(f"{prefix} **{name}** — {pts} pts{fl}")

        embed.add_field(name="Résultats", value="\n".join(lines_out), inline=False)
        if errors:
            embed.add_field(name="⚠️ Erreurs", value="\n".join(errors), inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Championship(bot))
