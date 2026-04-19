import os
import json
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord
from bs4 import BeautifulSoup

SITE_URL = os.getenv("RACES_SITE_URL", "http://82.165.167.165")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
DATA_FILE = "data/known_races.json"
PARIS = ZoneInfo("Europe/Paris")
TAG_COLORS = ("text-blue-400", "text-green-400", "text-orange-400")


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

    def _parse_races(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        races = []
        for article in soup.find_all("article"):
            time_el = article.find("time")
            if not time_el or not time_el.get("dateTime"):
                continue
            title_el = article.find("h3")
            desc_el = article.find("p", class_=lambda c: c and "line-clamp-2" in c)
            tag_els = article.find_all(
                "span",
                class_=lambda c: c and any(color in c for color in TAG_COLORS),
            )
            races.append({
                "id": time_el["dateTime"],
                "title": title_el.get_text(strip=True) if title_el else "?",
                "date": time_el["dateTime"],
                "tags": [t.get_text(strip=True) for t in tag_els],
                "description": desc_el.get_text(strip=True) if desc_el else "",
            })
        return races

    @tasks.loop(minutes=5)
    async def check_new_races(self):
        if not RACES_CHANNEL_ID:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    SITE_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    html = await resp.text()
        except Exception:
            return

        races = self._parse_races(html)
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
        embed = discord.Embed(
            title=f"🏁 Nouvelle course : {race['title']}",
            description=race.get("description") or "",
            color=0xE63946,
            url=SITE_URL,
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
