import os
import json
import logging
import aiohttp
import anthropic
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord
from discord import app_commands

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "")
RACES_STAFF_ROLE_ID = int(os.getenv("RACES_STAFF_ROLE_ID", "1424791316881211412"))
DATA_PREGRID = "data/pregrid.json"
DATA_MESSAGES = "data/race_messages.json"
DATA_REGISTRATIONS = "data/race_registrations.json"
PARIS = ZoneInfo("Europe/Paris")
EMBED_COLOR = 0xF4A261

DEFAULT_CONFIG = {"minutes_before": 10, "points_threshold": 10}


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _load_pregrid() -> dict:
    try:
        with open(DATA_PREGRID) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_pregrid(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_PREGRID, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_messages() -> dict:
    try:
        with open(DATA_MESSAGES) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _load_registrations() -> dict:
    try:
        with open(DATA_REGISTRATIONS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# ── Cog ──────────────────────────────────────────────────────────────────────

class Pregrid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_pregrid_loop.start()

    def cog_unload(self):
        self.check_pregrid_loop.cancel()

    # ── Permission check ─────────────────────────────────────────────────────

    def _is_staff(self, user: discord.Member) -> bool:
        return user.guild_permissions.manage_guild or any(
            r.id == RACES_STAFF_ROLE_ID for r in user.roles
        )

    # ── Site API calls ───────────────────────────────────────────────────────

    async def _fetch_by_discord(self, discord_ids: list[str]) -> list[dict]:
        if not discord_ids:
            return []
        ids_param = ",".join(discord_ids)
        url = f"{SITE_URL}/api/players/by-discord?discordIds={ids_param}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    url,
                    headers={"x-bot-secret": BOT_API_SECRET},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        logger.error("by-discord API — statut %s", r.status)
                        return []
                    return await r.json()
        except Exception as e:
            logger.error("Erreur by-discord API : %s", e)
            return []

    async def _fetch_ladder(self, car_class: str) -> list[dict]:
        url = f"{SITE_URL}/api/players/ladder?carClass={car_class}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    url,
                    headers={"x-bot-secret": BOT_API_SECRET},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        logger.error("ladder API — statut %s pour %s", r.status, car_class)
                        return []
                    return await r.json()
        except Exception as e:
            logger.error("Erreur ladder API (%s) : %s", car_class, e)
            return []

    # ── Laïus generation ─────────────────────────────────────────────────────

    async def _generate_class_laius(
        self,
        class_name: str,
        title: str,
        members: list[dict],
        profiles_by_id: dict,
        ladder: list[dict],
        config: dict,
    ) -> str | None:
        """Génère un laïus via Anthropic pour une classe. Retourne None si échec."""
        threshold = config.get("points_threshold", DEFAULT_CONFIG["points_threshold"])
        inscrits_ids = {m["id"] for m in members}

        # Construire les données par inscrit
        pilot_lines = []
        for member in members:
            profile = profiles_by_id.get(member["id"])
            if not profile:
                continue

            # Trouver les stats de cette classe dans le profil
            class_stat = next(
                (cs for cs in profile.get("classStats", []) if cs["carClass"] == class_name),
                None,
            )
            if not class_stat:
                continue

            pts = class_stat["ladderPoints"]
            tier = class_stat.get("xpTierName") or "—"

            concurrents_presents = [
                p for p in ladder
                if abs(p["ladderPoints"] - pts) <= threshold
                and p["discordId"] in inscrits_ids
                and p["discordId"] != member["id"]
            ]
            absents_fenetre = [
                p for p in ladder
                if abs(p["ladderPoints"] - pts) <= threshold
                and p["discordId"] not in inscrits_ids
            ]

            en_danger = any(p["ladderPoints"] < pts for p in concurrents_presents)
            peut_prendre_large = not any(p["ladderPoints"] > pts for p in concurrents_presents)

            situation_parts = []
            if peut_prendre_large and not en_danger:
                situation_parts.append("peut prendre du large")
            if en_danger:
                hunters = [p["username"] for p in concurrents_presents if p["ladderPoints"] < pts]
                situation_parts.append(f"chassé par {', '.join(hunters)}")
            if concurrents_presents:
                rivals = [p["username"] for p in concurrents_presents if p["ladderPoints"] >= pts]
                if rivals:
                    situation_parts.append(f"rivalité directe avec {', '.join(rivals)}")

            situation = " / ".join(situation_parts) if situation_parts else "course ouverte"
            pilot_lines.append(
                f"- {profile['username']} ({pts} pts, {tier}) : {situation}"
            )

        # Absents notables (présents dans au moins une fenêtre de points)
        absent_ids_in_windows = set()
        for member in members:
            profile = profiles_by_id.get(member["id"])
            if not profile:
                continue
            class_stat = next(
                (cs for cs in profile.get("classStats", []) if cs["carClass"] == class_name),
                None,
            )
            if not class_stat:
                continue
            pts = class_stat["ladderPoints"]
            for p in ladder:
                if (
                    abs(p["ladderPoints"] - pts) <= threshold
                    and p["discordId"] not in inscrits_ids
                ):
                    absent_ids_in_windows.add(p["discordId"])

        absent_lines = []
        seen_absent = set()
        for p in ladder:
            if p["discordId"] in absent_ids_in_windows and p["discordId"] not in seen_absent:
                seen_absent.add(p["discordId"])
                tier = p.get("xpTierName") or "—"
                absent_lines.append(f"- {p['username']} ({p['ladderPoints']} pts, {tier})")

        if not pilot_lines:
            return None

        minutes_before = config.get("minutes_before", DEFAULT_CONFIG["minutes_before"])
        user_prompt = (
            f"Classe : {class_name} — {title}\n"
            f"Seuil concurrents directs : ±{threshold} points ladder\n\n"
            f"Pilotes présents :\n" + "\n".join(pilot_lines)
        )
        if absent_lines:
            user_prompt += "\n\nAbsents notables dans les fenêtres de points :\n" + "\n".join(absent_lines)
        user_prompt += "\n\nRédige le laïus d'avant-course pour cette classe."

        try:
            client = anthropic.AsyncAnthropic()
            message = await client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=400,
                system=(
                    "Tu es le commentateur officiel de la ligue SimRacing PADS (Par amour du spin). "
                    "Tu rédiges des laïus d'avant-course en français, style journaliste sportif percutant. "
                    "Sois concis (5 à 8 phrases max), dynamique, mentionne les pilotes par leur nom. "
                    "Ne jamais inventer d'informations au-delà des données fournies. "
                    "Texte brut uniquement, pas de markdown."
                ),
                messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text
        except Exception as e:
            logger.error("Erreur Anthropic pour classe %s : %s", class_name, e)
            return None

    async def _post_laius(
        self,
        channel_id: int,
        config: dict,
        target_channel: discord.TextChannel | None = None,
        ephemeral_interaction: discord.Interaction | None = None,
    ):
        """Génère et poste les embeds de laïus pour un channel de course."""
        regs = _load_registrations()
        key = str(channel_id)
        if key not in regs:
            raise ValueError(f"Aucune inscription trouvée pour le channel {channel_id}")

        race_data = regs[key]
        title = race_data.get("title", "Course")
        classes_data: dict = race_data.get("classes", {})

        if not classes_data:
            raise ValueError("Aucune classe trouvée dans les inscriptions")

        minutes_before = config.get("minutes_before", DEFAULT_CONFIG["minutes_before"])
        embeds = []

        for class_name in sorted(classes_data.keys()):
            members = classes_data[class_name]
            if not members:
                continue

            discord_ids = [m["id"] for m in members]
            profiles_raw = await self._fetch_by_discord(discord_ids)
            ladder = await self._fetch_ladder(class_name)

            profiles_by_id = {p["discordId"]: p for p in profiles_raw if p.get("discordId")}

            laius_text = await self._generate_class_laius(
                class_name, title, members, profiles_by_id, ladder, config
            )

            if laius_text:
                description = laius_text
            else:
                # Fallback : liste des inscrits
                description = "\n".join(f"• {m['name']}" for m in members)
                logger.warning("Fallback pour classe %s (pas de laïus généré)", class_name)

            embed = discord.Embed(
                title=f"🏁 {class_name} — Enjeux de la course",
                description=description,
                color=EMBED_COLOR,
            )
            embed.set_footer(
                text=f"Départ dans {minutes_before} minutes · Bonne course à tous 🏎️"
            )
            embeds.append(embed)

        if not embeds:
            raise ValueError("Aucun embed à poster")

        if ephemeral_interaction:
            await ephemeral_interaction.followup.send(embeds=embeds, ephemeral=True)
        else:
            channel = target_channel or await self.bot.fetch_channel(channel_id)
            for embed in embeds:
                await channel.send(embed=embed)

    # ── Background task ──────────────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def check_pregrid_loop(self):
        now = datetime.now(PARIS)
        messages = _load_messages()
        pregrid = _load_pregrid()
        changed = False

        for guild_id_str, guild_data in pregrid.items():
            config = guild_data.get("config", DEFAULT_CONFIG)
            posted: list = guild_data.setdefault("posted", [])
            minutes_before = config.get("minutes_before", DEFAULT_CONFIG["minutes_before"])

            for _msg_id, race_data in messages.items():
                channel_id = str(race_data.get("channel_id", ""))
                if not channel_id or channel_id in posted:
                    continue
                if not race_data.get("date"):
                    continue

                regs = _load_registrations()
                if channel_id not in regs:
                    continue

                try:
                    race_dt = datetime.fromisoformat(
                        race_data["date"].replace("Z", "+00:00")
                    ).astimezone(PARIS)
                except ValueError:
                    continue

                delta = race_dt - now
                target = timedelta(minutes=minutes_before)
                if not (target - timedelta(minutes=1) <= delta <= target + timedelta(minutes=1)):
                    continue

                try:
                    await self._post_laius(int(channel_id), config)
                    posted.append(channel_id)
                    changed = True
                    logger.info("Laïus posté pour channel %s", channel_id)
                except Exception as e:
                    logger.error("Erreur laïus pour channel %s : %s", channel_id, e)

        if changed:
            _save_pregrid(pregrid)

    @check_pregrid_loop.before_loop
    async def before_pregrid(self):
        await self.bot.wait_until_ready()

    # ── Slash command group ──────────────────────────────────────────────────

    pregrid_group = app_commands.Group(
        name="pregrid",
        description="Gestion du laïus pré-grille",
    )

    @pregrid_group.command(
        name="config",
        description="Configure les paramètres du laïus pré-grille pour ce serveur",
    )
    @app_commands.describe(
        minutes="Minutes avant le départ pour poster le laïus (défaut : 10)",
        points="Seuil de points pour les concurrents directs (défaut : 10)",
    )
    async def pregrid_config(
        self,
        interaction: discord.Interaction,
        minutes: int,
        points: int,
    ):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Commande réservée au staff.", ephemeral=True
            )
            return

        pregrid = _load_pregrid()
        guild_id = str(interaction.guild_id)
        pregrid.setdefault(guild_id, {})["config"] = {
            "minutes_before": minutes,
            "points_threshold": points,
        }
        _save_pregrid(pregrid)

        embed = discord.Embed(
            title="✅ Pregrid configuré",
            color=EMBED_COLOR,
        )
        embed.add_field(name="⏱️ Minutes avant le départ", value=str(minutes), inline=True)
        embed.add_field(name="🎯 Seuil de points", value=str(points), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @pregrid_group.command(
        name="forcer",
        description="Force le post immédiat du laïus pour un channel de course",
    )
    @app_commands.describe(channel="Channel privé de la course")
    async def pregrid_forcer(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Commande réservée au staff.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)

        regs = _load_registrations()
        if str(channel.id) not in regs:
            await interaction.followup.send(
                f"❌ Aucune inscription trouvée pour {channel.mention}.", ephemeral=True
            )
            return

        pregrid = _load_pregrid()
        guild_id = str(interaction.guild_id)
        config = pregrid.get(guild_id, {}).get("config", DEFAULT_CONFIG)

        try:
            await self._post_laius(channel.id, config, target_channel=channel)
            await interaction.followup.send(
                f"✅ Laïus posté dans {channel.mention}.", ephemeral=True
            )
        except Exception as e:
            logger.error("pregrid forcer — erreur : %s", e)
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)

    @pregrid_group.command(
        name="apercu",
        description="Affiche le laïus en éphémère sans le poster dans le channel",
    )
    @app_commands.describe(channel="Channel privé de la course")
    async def pregrid_apercu(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Commande réservée au staff.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        regs = _load_registrations()
        if str(channel.id) not in regs:
            await interaction.followup.send(
                f"❌ Aucune inscription trouvée pour {channel.mention}.", ephemeral=True
            )
            return

        pregrid = _load_pregrid()
        guild_id = str(interaction.guild_id)
        config = pregrid.get(guild_id, {}).get("config", DEFAULT_CONFIG)

        try:
            await self._post_laius(
                channel.id, config, ephemeral_interaction=interaction
            )
        except Exception as e:
            logger.error("pregrid apercu — erreur : %s", e)
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Pregrid(bot))
