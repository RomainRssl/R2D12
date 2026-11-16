import asyncio
import logging
import os

import aiohttp
import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "")
LMU_CHANNEL_ID = int(os.getenv("LMU_CHANNEL_ID", "1571872951349813398"))

_SYNC_ENDPOINT = f"{SITE_URL}/api/endurance/bot-sync"
_HEADERS = {
    "x-bot-secret": BOT_API_SECRET,
    "Content-Type": "application/json",
}
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_BURST_DELAY = 60  # secondes


def _serialize_message(msg: discord.Message, *, msg_id: str | None = None) -> dict:
    """Sérialise un discord.Message (ou un snapshot) en dict JSON."""
    content = (msg.content or "")[:8000]
    embeds = [
        {
            "title": e.title if e.title else None,
            "description": e.description if e.description else None,
            "fields": [{"name": f.name, "value": f.value} for f in e.fields],
        }
        for e in msg.embeds
    ]
    return {
        "id": msg_id or str(msg.id),
        "timestamp": msg.created_at.isoformat(),
        "content": content,
        "embeds": embeds,
    }


async def _collect_entries(channel: discord.TextChannel) -> list[dict]:
    """Retourne jusqu'à 100 entrées depuis les 50 derniers messages du salon."""
    entries: list[dict] = []
    async for msg in channel.history(limit=50, oldest_first=False):
        entries.append(_serialize_message(msg))
        # Snapshots (transferts)
        snapshots = getattr(msg, "message_snapshots", None) or []
        for i, snap in enumerate(snapshots):
            entries.append(_serialize_message(snap, msg_id=f"{msg.id}-{i}"))
        if len(entries) >= 100:
            break
    return entries[:100]


class LmuSync(commands.Cog):
    """Écoute le salon « maj LMU » et transmet les messages au site PADS."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._burst_task: asyncio.Task | None = None
        self._hourly_sync.start()

    def cog_unload(self):
        self._hourly_sync.cancel()
        if self._burst_task and not self._burst_task.done():
            self._burst_task.cancel()

    # ── Envoi HTTP ────────────────────────────────────────────────────────────

    async def _send_to_site(self, entries: list[dict]) -> None:
        if not entries:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _SYNC_ENDPOINT,
                    json={"messages": entries},
                    headers=_HEADERS,
                    timeout=_TIMEOUT,
                ) as resp:
                    text = await resp.text()
                    if resp.status in (400, 401):
                        logger.error("lmu_sync — %s %s : %s", resp.status, _SYNC_ENDPOINT, text[:500])
                        return
                    if resp.status >= 400:
                        logger.error("lmu_sync — statut inattendu %s : %s", resp.status, text[:500])
                        return
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        logger.error("lmu_sync — réponse non-JSON : %s", text[:500])
                        return

        except aiohttp.ClientError as exc:
            logger.error("lmu_sync — erreur réseau : %s", exc)
            return
        except asyncio.TimeoutError:
            logger.error("lmu_sync — timeout")
            return

        # Logs
        messages_read: int = data.get("messagesRead", 0)
        created: list = data.get("created", [])
        filled: list = data.get("sessionsFilled", [])
        announced: list = data.get("announced", [])
        warning: str | None = data.get("warning")
        errors: list = data.get("errors", [])

        logger.info("lmu_sync — %d message(s) lus", messages_read)
        if created:
            logger.info("lmu_sync — week-ends créés : %s", created)
        if filled:
            logger.info("lmu_sync — sessions renseignées : %s", filled)
        if announced:
            logger.info("lmu_sync — annonces : %s", announced)
        if warning:
            logger.warning("lmu_sync — avertissement site : %s", warning)
        if errors:
            logger.warning("lmu_sync — erreurs site : %s", errors)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _fetch_and_send(self, reason: str) -> None:
        channel = self.bot.get_channel(LMU_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(LMU_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden) as exc:
                logger.error("lmu_sync — salon introuvable (%s) : %s", LMU_CHANNEL_ID, exc)
                return
        entries = await _collect_entries(channel)
        logger.debug("lmu_sync — %s : %d entrée(s) collectée(s)", reason, len(entries))
        await self._send_to_site(entries)

    async def _burst_wait_and_send(self) -> None:
        """Attend la fin de la rafale puis envoie."""
        await asyncio.sleep(_BURST_DELAY)
        await self._fetch_and_send("burst")
        self._burst_task = None

    def _schedule_burst(self) -> None:
        if self._burst_task and not self._burst_task.done():
            # Rafale en cours — réinitialise le délai
            self._burst_task.cancel()
        self._burst_task = asyncio.create_task(self._burst_wait_and_send())

    # ── Listeners ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("lmu_sync — rattrapage au démarrage")
        await self._fetch_and_send("ready")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id != LMU_CHANNEL_ID:
            return
        self._schedule_burst()

    @commands.Cog.listener()
    async def on_message_edit(self, _before: discord.Message, after: discord.Message):
        if after.channel.id != LMU_CHANNEL_ID:
            return
        self._schedule_burst()

    # ── Filet de sécurité horaire ─────────────────────────────────────────────

    @tasks.loop(hours=1)
    async def _hourly_sync(self):
        await self._fetch_and_send("hourly")

    @_hourly_sync.before_loop
    async def _before_hourly(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(LmuSync(bot))
