"""
Cog splits — Clôture des inscriptions et annonce multi-splits.

Endpoints consommés (PADS site) :
  POST {SITE_URL}/api/events/{id}/close   (Authorization: Bearer BOT_API_SECRET)
  GET  {SITE_URL}/api/events/upcoming     (Authorization: Bearer BOT_API_SECRET)
      → désactivé proprement si 404 (log + skip, pas de crash)
"""

import os
import json
import logging
import aiohttp
from datetime import datetime, timedelta, timezone
from discord.ext import commands, tasks
import discord

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))

DATA_CLOSED = "data/closed_races.json"


# ── Persistance des courses déjà clôturées ─────────────────────────


def _load_closed() -> set:
    try:
        with open(DATA_CLOSED) as f:
            return set(json.load(f).get("ids", []))
    except FileNotFoundError:
        return set()


def _save_closed(ids: set):
    os.makedirs("data", exist_ok=True)
    with open(DATA_CLOSED, "w") as f:
        json.dump({"ids": list(ids)}, f)


# ── Helpers embed ──────────────────────────────────────────────────


def _split_color(index: int) -> int:
    """Gold / Silver / Bronze pour les 3 premiers splits, bleu ensuite."""
    palette = [0xFFD700, 0xC0C0C0, 0xCD7F32]
    return palette[index - 1] if 1 <= index <= 3 else 0x5865F2


def _add_class_fields(embed: discord.Embed, class_name: str, drivers: list) -> None:
    """
    Ajoute un ou plusieurs champs pour une classe.
    Découpe la liste en chunks ≤ 1020 chars pour respecter la limite Discord.
    """
    nb = len(drivers)
    title = f"{class_name} ({nb})"

    if not drivers:
        embed.add_field(name=title, value="*Aucun pilote*", inline=False)
        return

    mentions = [
        f"<@{d['discordId']}>" if d.get("discordId") else d.get("pseudoLmu", "?")
        for d in drivers
    ]

    chunks: list[str] = []
    current = ""
    for token in (m + " " for m in mentions):
        if len(current) + len(token) > 1020:
            chunks.append(current.rstrip())
            current = token
        else:
            current += token
    if current.strip():
        chunks.append(current.rstrip())

    for i, chunk in enumerate(chunks):
        embed.add_field(
            name=title if i == 0 else f"{class_name} (suite)",
            value=chunk,
            inline=False,
        )


# ── Fonction principale ─────────────────────────────────────────────


async def cloturer_et_annoncer(
    event_id: str,
    channel: discord.abc.Messageable | None,
    bot: commands.Bot,
) -> str:
    """
    POST /api/events/{event_id}/close → parse les splits → poste un embed par split.

    Retourne :
      "manual"       si splits == []  (mode manuel, aucune annonce postée)
      message ✅/❌  sinon
    """
    if not BOT_API_SECRET:
        return "❌ BOT_API_SECRET non configuré."

    url = f"{SITE_URL}/api/events/{event_id}/close"
    headers = {
        "Authorization": f"Bearer {BOT_API_SECRET}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    logger.error("close %s → HTTP 401 (token invalide)", event_id)
                    return "❌ Token invalide (401) — vérifier BOT_API_SECRET."
                if resp.status == 404:
                    logger.error("close %s → HTTP 404", event_id)
                    return f"❌ Course `{event_id}` introuvable (404)."
                if resp.status >= 500:
                    body = await resp.text()
                    logger.error("close %s → HTTP %s : %s", event_id, resp.status, body[:200])
                    return f"❌ Erreur serveur ({resp.status}) pour `{event_id}`."
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error("close %s → HTTP %s : %s", event_id, resp.status, body[:200])
                    return f"❌ Erreur API ({resp.status}) pour `{event_id}`."
                data = await resp.json()
    except aiohttp.ServerTimeoutError:
        logger.error("cloturer_et_annoncer timeout pour %s", event_id)
        return f"❌ Timeout en appelant l'API pour `{event_id}`."
    except Exception as e:
        logger.error("cloturer_et_annoncer réseau : %s", e)
        return f"❌ Impossible de joindre l'API : {e}"

    race_name = data.get("raceName", event_id)
    splits = data.get("splits", [])

    # Mode manuel : splits vide → aucune annonce
    if not splits:
        logger.info("Event %s en mode manuel (splits=[]) — aucune annonce.", event_id)
        return "manual"

    # Résoudre le channel de destination
    target = channel
    if target is None and RACES_CHANNEL_ID:
        try:
            target = await bot.fetch_channel(RACES_CHANNEL_ID)
        except Exception as e:
            logger.warning("fetch_channel %s : %s", RACES_CHANNEL_ID, e)

    if target is None:
        return (
            f"✅ Splits calculés pour « {race_name} » "
            "mais aucun channel disponible pour l'annonce."
        )

    for split in splits:
        idx = split.get("index", 1)          # 1-based dans la réponse API
        label = split.get("label", f"Split {idx}")
        server_name = split.get("serverName", "")
        password = split.get("password", "")
        classes = split.get("classes", [])

        embed = discord.Embed(
            title=f"🏁 {race_name} — {label} (Split {idx})",
            color=_split_color(idx),
        )
        embed.add_field(name="🖥️ Serveur", value=server_name or "—", inline=True)
        embed.add_field(
            name="🔑 Mot de passe",
            value=f"`{password}`" if password else "—",
            inline=True,
        )
        for cls in classes:
            _add_class_fields(embed, cls.get("className", "?"), cls.get("drivers", []))

        embed.set_footer(text="Par amour du spin · Bonne course ! 🏎️")

        try:
            await target.send(embed=embed)
        except Exception as e:
            logger.error("Post embed split %d pour %s : %s", idx, event_id, e)

    closed = _load_closed()
    closed.add(str(event_id))
    _save_closed(closed)

    return f"✅ {len(splits)} split(s) annoncé(s) pour « {race_name} »."


# ── Cog ────────────────────────────────────────────────────────────


class Splits(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._upcoming_ok: bool | None = None  # None = pas encore sondé
        self.check_closures.start()

    def cog_unload(self):
        self.check_closures.cancel()

    async def _probe_upcoming(self) -> bool:
        """
        Sonde GET /api/events/upcoming une seule fois.
        404 → retourne False (clôture auto désactivée, log clair).
        Autre erreur → retourne False (désactivée jusqu'au prochain redémarrage).
        """
        url = f"{SITE_URL}/api/events/upcoming"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    url,
                    headers={"Authorization": f"Bearer {BOT_API_SECRET}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 404:
                        logger.warning(
                            "GET /api/events/upcoming → 404 — "
                            "clôture automatique désactivée. "
                            "Utilisez /cloturer pour clôturer manuellement."
                        )
                        return False
                    logger.info(
                        "GET /api/events/upcoming → HTTP %s (clôture auto activée)",
                        resp.status,
                    )
                    return True
        except Exception as e:
            logger.warning(
                "Sonde /api/events/upcoming échouée (%s) — "
                "clôture auto désactivée jusqu'au prochain redémarrage.",
                e,
            )
            return False

    # ── Loop auto-clôture ──────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def check_closures(self):
        """
        Toutes les minutes :
          1. Sonde l'endpoint au premier appel.
          2. Récupère les courses à venir.
          3. Clôture celles dont now(UTC) >= startTime - closeOffsetHours.
        Exceptions catchées — ne tue pas la tâche.
        """
        if self._upcoming_ok is None:
            self._upcoming_ok = await self._probe_upcoming()

        if not self._upcoming_ok or not BOT_API_SECRET:
            return

        closed_ids = _load_closed()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{SITE_URL}/api/events/upcoming",
                    headers={"Authorization": f"Bearer {BOT_API_SECRET}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "GET /api/events/upcoming → HTTP %s (skip)", resp.status
                        )
                        return
                    races = await resp.json()
        except Exception as e:
            logger.warning("check_closures réseau : %s (skip)", e)
            return

        now = datetime.now(timezone.utc)
        changed = False

        for race in races:
            event_id = str(race.get("id", ""))
            if not event_id or event_id in closed_ids:
                continue

            if race.get("registrationsClosed"):
                closed_ids.add(event_id)
                changed = True
                continue

            try:
                start_time = datetime.fromisoformat(
                    race["startTime"].replace("Z", "+00:00")
                )
            except (KeyError, ValueError):
                continue

            close_at = start_time - timedelta(hours=int(race.get("closeOffsetHours", 1)))

            if now >= close_at:
                logger.info(
                    "Auto-clôture event %s (%s)", event_id, race.get("title", "")
                )
                try:
                    result = await cloturer_et_annoncer(
                        event_id, channel=None, bot=self.bot
                    )
                    logger.info("Auto-clôture résultat : %s", result)
                    closed_ids.add(event_id)
                    changed = True
                except Exception as e:
                    logger.error("Auto-clôture event %s : %s", event_id, e)

        if changed:
            _save_closed(closed_ids)

    @check_closures.before_loop
    async def before_check_closures(self):
        await self.bot.wait_until_ready()

    # ── Slash command /cloturer ────────────────────────────────────

    @discord.app_commands.command(
        name="cloturer",
        description="Clôture les inscriptions et annonce les splits pour une course",
    )
    @discord.app_commands.describe(event_id="Identifiant de la course (ex: cm9abc123)")
    @discord.app_commands.default_permissions(manage_guild=True)
    async def cloturer_cmd(
        self, interaction: discord.Interaction, event_id: str
    ):
        await interaction.response.defer(ephemeral=True)
        result = await cloturer_et_annoncer(
            event_id=event_id,
            channel=interaction.channel,  # type: ignore[arg-type]
            bot=self.bot,
        )
        if result == "manual":
            await interaction.followup.send(
                "✅ Inscriptions fermées (mode manuel — pas d'annonce auto).",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(result, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Splits(bot))
