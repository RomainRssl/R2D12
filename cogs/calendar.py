import os
import json
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord

RACES_API_URL = os.getenv("RACES_API_URL", "http://82.165.167.165/api/races")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
DATA_FILE = "data/known_races.json"
PARIS = ZoneInfo("Europe/Paris")


class Calendar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_new_races.start()

    def cog_unload(self):
        self.check_new_races.cancel()

    def _load_known(self) -> set[str] | None:
        try:
            with open(DATA_FILE) as f:
                return set(json.load(f).get("known_ids", []))
        except FileNotFoundError:
            return None  # None = premier démarrage, pas d'annonce

    def _save_known(self, ids: set[str]):
        with open(DATA_FILE, "w") as f:
            json.dump({"known_ids": list(ids)}, f)

    @tasks.loop(minutes=5)
    async def check_new_races(self):
        if not RACES_CHANNEL_ID:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    RACES_API_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    races = await resp.json()
        except Exception:
            return

        known = self._load_known()
        current_ids = {r["id"] for r in races}

        if known is None:
            self._save_known(current_ids)
            return

        new_races = [r for r in races if r["id"] not in known]
        if not new_races:
            return

        channel = self.bot.get_channel(RACES_CHANNEL_ID)
        if not channel:
            return

        for race in new_races:
            await channel.send(embed=self._build_embed(race))
            known.add(race["id"])

        self._save_known(known)

    def _build_embed(self, race: dict) -> discord.Embed:
        dt = datetime.fromisoformat(race["date"].replace("Z", "+00:00")).astimezone(PARIS)
        date_str = dt.strftime("%A %d %B %Y à %H:%M").capitalize()
        site_url = RACES_API_URL.replace("/api/races", "")
        embed = discord.Embed(
            title=f"🏁 Nouvelle course : {race['title']}",
            description=race.get("description") or "",
            color=0xE63946,
            url=site_url,
        )
        embed.add_field(name="📅 Date", value=date_str, inline=False)
        if race.get("tags"):
            embed.add_field(name="🏎️ Infos", value=" · ".join(race["tags"]), inline=False)
        embed.set_footer(text="Par amour du spin")
        return embed

    @check_new_races.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Calendar(bot))
