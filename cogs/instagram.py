import logging
import os
import json
import aiohttp
import xml.etree.ElementTree as ET
from discord.ext import commands, tasks
import discord

logger = logging.getLogger("r2d12.instagram")

DATA_FILE = "data/instagram.json"
INSTAGRAM_USERNAME = "paramourduspin_"
CHANNEL_ID = 1575170929544270046
# RSS feed via rss.app — replace with your generated feed URL if needed
RSS_URL = f"https://rss.app/feeds/_instagram_{INSTAGRAM_USERNAME}.xml"
POLL_INTERVAL_MINUTES = 15


def _load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_post_id": None}


def _save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class Instagram(commands.Cog):
    """Poste automatiquement les nouveaux posts Instagram dans un channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_instagram.start()

    def cog_unload(self):
        self.poll_instagram.cancel()

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def poll_instagram(self):
        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            logger.warning("Channel Instagram introuvable (id=%s)", CHANNEL_ID)
            return

        data = _load_data()
        last_id = data.get("last_post_id")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RSS_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.warning("RSS Instagram: status %s", resp.status)
                        return
                    text = await resp.text()
        except Exception as e:
            logger.error("Erreur fetch RSS Instagram: %s", e)
            return

        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            logger.error("Erreur parsing RSS: %s", e)
            return

        ns = {"media": "http://search.yahoo.com/mrss/"}
        items = root.findall(".//item")
        if not items:
            return

        # Find new posts (items newer than last seen)
        new_items = []
        for item in items:
            guid = item.findtext("guid") or item.findtext("link")
            if guid == last_id:
                break
            new_items.append(item)

        if not new_items:
            return

        # Post from oldest to newest
        new_items.reverse()
        for item in new_items:
            guid = item.findtext("guid") or item.findtext("link")
            link = item.findtext("link") or ""
            description = item.findtext("description") or ""
            # Try to extract image from media:content or enclosure
            image_url = None
            media_content = item.find("media:content", ns)
            if media_content is not None:
                image_url = media_content.get("url")
            if image_url is None:
                enclosure = item.find("enclosure")
                if enclosure is not None:
                    image_url = enclosure.get("url")

            embed = discord.Embed(
                description=description[:2048] if description else "",
                color=discord.Color.from_rgb(225, 48, 108),  # Instagram pink
                url=link,
            )
            embed.set_author(
                name=f"@{INSTAGRAM_USERNAME}",
                url=f"https://www.instagram.com/{INSTAGRAM_USERNAME}/",
                icon_url="https://www.instagram.com/favicon.ico",
            )
            if image_url:
                embed.set_image(url=image_url)
            embed.set_footer(text="Instagram")

            try:
                await channel.send(embed=embed)
            except discord.HTTPException as e:
                logger.error("Erreur envoi post Instagram: %s", e)

        # Save most recent post id
        newest_guid = items[0].findtext("guid") or items[0].findtext("link")
        data["last_post_id"] = newest_guid
        _save_data(data)
        logger.info("Instagram: %d nouveau(x) post(s) envoyés", len(new_items))

    @poll_instagram.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Instagram(bot))
