import os
import json
import re
import unicodedata
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord
from bs4 import BeautifulSoup

SITE_URL = os.getenv("RACES_SITE_URL", "http://82.165.167.165")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
RACES_CATEGORY_ID = int(os.getenv("RACES_CATEGORY_ID", "1399427481945247817"))
DATA_FILE = "data/known_races.json"
DATA_MESSAGES = "data/race_messages.json"
PARIS = ZoneInfo("Europe/Paris")
TAG_COLORS = ("text-blue-400", "text-green-400", "text-orange-400")
REACTION_EMOJI = "🏁"


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


class Calendar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_new_races.start()

    def cog_unload(self):
        self.check_new_races.cancel()

    # ── Known races (dédup scraping) ──────────────────────────────

    def _load_known(self) -> set[str] | None:
        try:
            with open(DATA_FILE) as f:
                return set(json.load(f).get("known_ids", []))
        except FileNotFoundError:
            return None

    def _save_known(self, ids: set[str]):
        with open(DATA_FILE, "w") as f:
            json.dump({"known_ids": list(ids)}, f)

    # ── Mapping message → rôle/salon ──────────────────────────────

    def _load_messages(self) -> dict:
        try:
            with open(DATA_MESSAGES) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save_message(self, message_id: str, data: dict):
        messages = self._load_messages()
        messages[message_id] = data
        with open(DATA_MESSAGES, "w") as f:
            json.dump(messages, f)

    # ── Scraping HTML ─────────────────────────────────────────────

    def _parse_races(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        races = []
        for article in soup.find_all("article"):
            time_el = article.find("time")
            if not time_el or not time_el.get("datetime"):
                continue
            title_el = article.find("h3")
            desc_el = article.find("p", class_=lambda c: c and "line-clamp-2" in c)
            tag_els = article.find_all(
                "span",
                class_=lambda c: c and any(color in c for color in TAG_COLORS),
            )
            races.append({
                "id": time_el["datetime"],
                "title": title_el.get_text(strip=True) if title_el else "?",
                "date": time_el["datetime"],
                "tags": [t.get_text(strip=True) for t in tag_els],
                "description": desc_el.get_text(strip=True) if desc_el else "",
            })
        return races

    # ── Annonce d'une nouvelle course ─────────────────────────────

    async def _announce_race(self, race: dict):
        channel = self.bot.get_channel(RACES_CHANNEL_ID)
        if not channel:
            return

        guild = channel.guild

        role = await guild.create_role(name=race["title"], mentionable=True)

        category = guild.get_channel(RACES_CATEGORY_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        race_channel = await guild.create_text_channel(
            name=_slugify(race["title"]),
            category=category,
            overwrites=overwrites,
        )

        msg = await channel.send(embed=self._build_embed(race, race_channel))
        await msg.add_reaction(REACTION_EMOJI)

        self._save_message(str(msg.id), {
            "role_id": role.id,
            "channel_id": race_channel.id,
            "title": race["title"],
        })

    # ── Tâche planifiée ───────────────────────────────────────────

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

        for race in new_races:
            await self._announce_race(race)
            known.add(race["id"])

        self._save_known(known)

    @check_new_races.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── Réaction ajoutée → attribuer le rôle ─────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        messages = self._load_messages()
        if str(payload.message_id) not in messages:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        race_data = messages[str(payload.message_id)]
        role = guild.get_role(race_data["role_id"])
        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return
        if role and member:
            await member.add_roles(role)

    # ── Réaction retirée → retirer le rôle ───────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        messages = self._load_messages()
        if str(payload.message_id) not in messages:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        race_data = messages[str(payload.message_id)]
        role = guild.get_role(race_data["role_id"])
        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return
        if role and member:
            await member.remove_roles(role)

    # ── Construction de l'embed ───────────────────────────────────

    def _build_embed(self, race: dict, race_channel=None) -> discord.Embed:
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
        if race_channel:
            embed.add_field(name="💬 Salon", value=race_channel.mention, inline=False)
        embed.add_field(
            name="📌 Inscription",
            value=f"Réagissez avec {REACTION_EMOJI} pour accéder au salon de la course",
            inline=False,
        )
        embed.set_footer(text="Par amour du spin")
        return embed


async def setup(bot):
    await bot.add_cog(Calendar(bot))
