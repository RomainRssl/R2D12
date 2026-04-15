import json
import os
import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

SESSIONS_FILE = "data/sessions.json"


def load_data() -> dict:
    if not os.path.exists(SESSIONS_FILE):
        return {}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_id(data: dict, guild_id: str) -> str:
    sessions = data.get(guild_id, {}).get("sessions", {})
    existing = [int(k) for k in sessions if k.isdigit()]
    return str(max(existing, default=0) + 1)


def build_session_embed(session: dict, session_id: str, guild: discord.Guild) -> discord.Embed:
    starts_at = datetime.datetime.fromisoformat(session["starts_at"])
    now = datetime.datetime.utcnow()
    passed = starts_at < now

    color = discord.Color.greyple() if passed else discord.Color.green()
    embed = discord.Embed(
        title=f"{'🏁' if passed else '🟢'} Session #{session_id} — {session['titre']}",
        color=color,
    )
    embed.add_field(name="🎮 Simulateur", value=session["simulateur"], inline=True)
    embed.add_field(name="📍 Piste", value=session["piste"], inline=True)
    embed.add_field(name="🚗 Voiture", value=session.get("voiture") or "Libre", inline=True)
    embed.add_field(
        name="🗓️ Date & Heure",
        value=discord.utils.format_dt(starts_at, style="F") + f"\n({discord.utils.format_dt(starts_at, style='R')})",
        inline=False,
    )

    inscrit_ids = session.get("inscrits", [])
    max_places = session.get("max_places")
    places_str = f"{len(inscrit_ids)}"
    if max_places:
        places_str += f"/{max_places}"
    embed.add_field(name=f"👥 Inscrits ({places_str})", value=_format_inscrits(inscrit_ids, guild) or "_Aucun inscrit_", inline=False)

    organisateur = guild.get_member(int(session["organisateur_id"]))
    embed.set_footer(text=f"Organisé par {organisateur.display_name if organisateur else 'Inconnu'} • ID : {session_id}")
    return embed


def _format_inscrits(ids: list, guild: discord.Guild) -> str:
    names = []
    for uid in ids:
        m = guild.get_member(int(uid))
        names.append(m.display_name if m else f"ID {uid}")
    return "\n".join(f"• {n}" for n in names) if names else ""


session_group = app_commands.Group(name="session", description="Organisation de sessions de roulage")


class Sessions(commands.Cog):
    """Gestion des sessions de roulage avec rappels automatiques."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminded: set[str] = set()  # guild_key:session_id déjà rappelés
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    # ── Rappels automatiques ──────────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def check_reminders(self):
        data = load_data()
        now = datetime.datetime.utcnow()

        for guild_id, guild_data in data.items():
            announce_channel_id = guild_data.get("announce_channel_id")
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue

            for session_id, session in guild_data.get("sessions", {}).items():
                if session.get("cancelled"):
                    continue
                starts_at = datetime.datetime.fromisoformat(session["starts_at"])
                delta = (starts_at - now).total_seconds()
                remind_key = f"{guild_id}:{session_id}"

                # Rappel 1h avant
                if 0 < delta <= 3600 and remind_key not in self.reminded:
                    self.reminded.add(remind_key)
                    channel_id = announce_channel_id or session.get("channel_id")
                    channel = guild.get_channel(channel_id) if channel_id else None
                    if channel:
                        inscrits = session.get("inscrits", [])
                        mentions = " ".join(f"<@{uid}>" for uid in inscrits) if inscrits else ""
                        embed = discord.Embed(
                            title=f"⏰ Rappel — Session #{session_id} dans 1 heure !",
                            description=f"**{session['titre']}** commence bientôt.",
                            color=discord.Color.orange(),
                        )
                        embed.add_field(name="🎮 Simulateur", value=session["simulateur"], inline=True)
                        embed.add_field(name="📍 Piste", value=session["piste"], inline=True)
                        embed.add_field(name="Heure", value=discord.utils.format_dt(starts_at, style="t"), inline=True)
                        content = f"📣 {mentions}" if mentions else None
                        await channel.send(content=content, embed=embed)

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── Commandes ─────────────────────────────────────────────────────────────

    @session_group.command(name="creer", description="Créer une session de roulage")
    @app_commands.describe(
        titre="Titre de la session",
        date="Date au format JJ/MM/AAAA (ex: 25/12/2025)",
        heure="Heure au format HH:MM UTC (ex: 20:30)",
        simulateur="Simulateur (ex: Assetto Corsa, iRacing, F1 24...)",
        piste="Circuit (ex: Spa-Francorchamps)",
        voiture="Voiture ou classe (optionnel)",
        max_places="Nombre maximum de pilotes (optionnel)",
    )
    async def session_create(
        self, interaction: discord.Interaction,
        titre: str, date: str, heure: str,
        simulateur: str, piste: str,
        voiture: str = None,
        max_places: app_commands.Range[int, 2, 100] = None,
    ):
        try:
            starts_at = datetime.datetime.strptime(f"{date} {heure}", "%d/%m/%Y %H:%M")
        except ValueError:
            await interaction.response.send_message(
                "Format de date/heure invalide. Utilisez `JJ/MM/AAAA` et `HH:MM`.", ephemeral=True
            )
            return

        if starts_at < datetime.datetime.utcnow():
            await interaction.response.send_message("La date de la session est déjà passée.", ephemeral=True)
            return

        data = load_data()
        guild_key = str(interaction.guild_id)
        data.setdefault(guild_key, {"announce_channel_id": None, "sessions": {}})
        sid = next_id(data, guild_key)

        session = {
            "titre": titre,
            "simulateur": simulateur,
            "piste": piste,
            "voiture": voiture,
            "starts_at": starts_at.isoformat(),
            "max_places": max_places,
            "organisateur_id": str(interaction.user.id),
            "inscrits": [str(interaction.user.id)],
            "channel_id": interaction.channel_id,
            "cancelled": False,
        }
        data[guild_key]["sessions"][sid] = session
        save_data(data)

        embed = build_session_embed(session, sid, interaction.guild)
        view = SessionView(guild_key, sid)
        await interaction.response.send_message(embed=embed, view=view)

    @session_group.command(name="liste", description="Voir les prochaines sessions")
    async def session_list(self, interaction: discord.Interaction):
        data = load_data()
        sessions = data.get(str(interaction.guild_id), {}).get("sessions", {})
        now = datetime.datetime.utcnow()

        upcoming = [
            (sid, s) for sid, s in sessions.items()
            if not s.get("cancelled") and datetime.datetime.fromisoformat(s["starts_at"]) >= now
        ]
        upcoming.sort(key=lambda x: x[1]["starts_at"])

        if not upcoming:
            await interaction.response.send_message("Aucune session à venir.", ephemeral=True)
            return

        embed = discord.Embed(title="Prochaines sessions", color=discord.Color.green())
        for sid, s in upcoming[:10]:
            starts_at = datetime.datetime.fromisoformat(s["starts_at"])
            nb = len(s.get("inscrits", []))
            places = f"{nb}/{s['max_places']}" if s.get("max_places") else str(nb)
            embed.add_field(
                name=f"#{sid} — {s['titre']}",
                value=(
                    f"🎮 {s['simulateur']} • 📍 {s['piste']}\n"
                    f"🗓️ {discord.utils.format_dt(starts_at, style='f')} ({discord.utils.format_dt(starts_at, style='R')})\n"
                    f"👥 {places} inscrits"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @session_group.command(name="info", description="Voir les détails d'une session")
    @app_commands.describe(session_id="Numéro de la session")
    async def session_info(self, interaction: discord.Interaction, session_id: str):
        data = load_data()
        session = data.get(str(interaction.guild_id), {}).get("sessions", {}).get(session_id)
        if not session:
            await interaction.response.send_message(f"Session `#{session_id}` introuvable.", ephemeral=True)
            return
        embed = build_session_embed(session, session_id, interaction.guild)
        starts_at = datetime.datetime.fromisoformat(session["starts_at"])
        view = SessionView(str(interaction.guild_id), session_id) if starts_at > datetime.datetime.utcnow() else None
        await interaction.response.send_message(embed=embed, view=view)

    @session_group.command(name="annuler", description="Annuler une session que vous avez créée")
    @app_commands.describe(session_id="Numéro de la session à annuler")
    async def session_cancel(self, interaction: discord.Interaction, session_id: str):
        data = load_data()
        guild_key = str(interaction.guild_id)
        session = data.get(guild_key, {}).get("sessions", {}).get(session_id)
        if not session:
            await interaction.response.send_message(f"Session `#{session_id}` introuvable.", ephemeral=True)
            return
        is_organizer = session["organisateur_id"] == str(interaction.user.id)
        is_admin = interaction.user.guild_permissions.manage_guild
        if not is_organizer and not is_admin:
            await interaction.response.send_message("Seul l'organisateur ou un admin peut annuler une session.", ephemeral=True)
            return
        session["cancelled"] = True
        save_data(data)
        await interaction.response.send_message(f"Session **#{session_id} — {session['titre']}** annulée.", ephemeral=True)

    @session_group.command(name="configurer", description="Définir le salon d'annonces des sessions (rappels)")
    @app_commands.describe(salon="Salon où envoyer les rappels de sessions")
    @app_commands.default_permissions(manage_guild=True)
    async def session_config(self, interaction: discord.Interaction, salon: discord.TextChannel):
        data = load_data()
        data.setdefault(str(interaction.guild_id), {"announce_channel_id": None, "sessions": {}})["announce_channel_id"] = salon.id
        save_data(data)
        await interaction.response.send_message(f"Rappels de sessions configurés dans {salon.mention}.", ephemeral=True)


class SessionView(discord.ui.View):
    def __init__(self, guild_id: str, session_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.session_id = session_id

    @discord.ui.button(label="✅ S'inscrire / Se désinscrire", style=discord.ButtonStyle.success, custom_id="session:toggle")
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        session = data.get(self.guild_id, {}).get("sessions", {}).get(self.session_id)
        if not session:
            await interaction.response.send_message("Session introuvable.", ephemeral=True)
            return
        starts_at = datetime.datetime.fromisoformat(session["starts_at"])
        if starts_at < datetime.datetime.utcnow():
            await interaction.response.send_message("Cette session est déjà passée.", ephemeral=True)
            return

        user_key = str(interaction.user.id)
        inscrits = session.setdefault("inscrits", [])
        max_places = session.get("max_places")

        if user_key in inscrits:
            inscrits.remove(user_key)
            save_data(data)
            embed = build_session_embed(session, self.session_id, interaction.guild)
            await interaction.response.edit_message(embed=embed)
            await interaction.followup.send("Vous vous êtes désinscrit de la session.", ephemeral=True)
        else:
            if max_places and len(inscrits) >= max_places:
                await interaction.response.send_message("La session est complète.", ephemeral=True)
                return
            inscrits.append(user_key)
            save_data(data)
            embed = build_session_embed(session, self.session_id, interaction.guild)
            await interaction.response.edit_message(embed=embed)
            await interaction.followup.send("Vous êtes inscrit à la session !", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = Sessions(bot)
    bot.tree.add_command(session_group)
    await bot.add_cog(cog)
