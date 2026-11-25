import logging
import os
import json
import asyncio
import datetime
import requests
import discord
from discord import app_commands
from discord.ext import commands, tasks
from http.cookiejar import MozillaCookieJar

logger = logging.getLogger("r2d12.instagram")

DATA_FILE = "data/instagram.json"
INSTAGRAM_USERNAME = "paramourduspin_"
CHANNEL_ID = 1575170929544270046
POLL_INTERVAL_MINUTES = 15
BACKFILL_COUNT = 10

IG_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "data/ig_cookies.txt")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://www.instagram.com/{INSTAGRAM_USERNAME}/",
}


def _load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sent_shortcodes": []}


def _save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    if os.path.exists(IG_COOKIES_FILE):
        jar = MozillaCookieJar()
        try:
            jar.load(IG_COOKIES_FILE, ignore_discard=True, ignore_expires=True)
            session.cookies.update(jar)
            logger.info("Instagram: cookies chargés depuis %s (%d cookies)", IG_COOKIES_FILE, len(list(jar)))
        except Exception as e:
            logger.warning("Instagram: échec chargement cookies: %s", e)
    else:
        logger.warning("Instagram: fichier cookies introuvable: %s", IG_COOKIES_FILE)
    return session


def _fetch_posts(count: int) -> list[dict]:
    session = _make_session()
    # Instagram internal API for profile posts
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={INSTAGRAM_USERNAME}"
    try:
        resp = session.get(url, timeout=15)
        logger.info("Instagram API status: %s", resp.status_code)
        if resp.status_code != 200:
            logger.error("Instagram API: status %s, body: %s", resp.status_code, resp.text[:300])
            return []
        data = resp.json()
    except Exception as e:
        logger.error("Instagram API: erreur requête: %s", e)
        return []

    try:
        edges = (
            data["data"]["user"]["edge_owner_to_timeline_media"]["edges"]
        )
    except (KeyError, TypeError) as e:
        logger.error("Instagram API: structure inattendue: %s | data=%s", e, str(data)[:300])
        return []

    posts = []
    for edge in edges[:count]:
        node = edge.get("node", {})
        shortcode = node.get("shortcode", "")
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = caption_edges[0]["node"]["text"] if caption_edges else ""
        timestamp = node.get("taken_at_timestamp", 0)
        is_video = node.get("is_video", False)
        image_url = node.get("display_url", "")
        posts.append({
            "shortcode": shortcode,
            "url": f"https://www.instagram.com/p/{shortcode}/",
            "caption": caption,
            "image_url": image_url,
            "timestamp": datetime.datetime.utcfromtimestamp(timestamp).isoformat(),
            "is_video": is_video,
        })
    return posts


def _build_embed(post: dict) -> discord.Embed:
    caption = post["caption"][:2048] if post["caption"] else ""
    embed = discord.Embed(
        description=caption,
        color=discord.Color.from_rgb(225, 48, 108),
        url=post["url"],
    )
    embed.set_author(
        name=f"@{INSTAGRAM_USERNAME}",
        url=f"https://www.instagram.com/{INSTAGRAM_USERNAME}/",
        icon_url="https://www.instagram.com/favicon.ico",
    )
    if post.get("image_url") and not post.get("is_video"):
        embed.set_image(url=post["image_url"])
    ts = datetime.datetime.fromisoformat(post["timestamp"])
    embed.timestamp = ts
    embed.set_footer(text="Instagram")
    return embed


class Instagram(commands.Cog):
    """Poste automatiquement les nouveaux posts Instagram dans un channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_instagram.start()

    def cog_unload(self):
        self.poll_instagram.cancel()

    async def _send_posts(self, channel: discord.TextChannel, posts: list[dict], data: dict):
        sent = data.setdefault("sent_shortcodes", [])
        for post in posts:
            sc = post["shortcode"]
            if sc in sent:
                continue
            embed = _build_embed(post)
            try:
                await channel.send(embed=embed)
                sent.append(sc)
                _save_data(data)
                await asyncio.sleep(1)
            except discord.HTTPException as e:
                logger.error("Erreur envoi post Instagram %s: %s", sc, e)

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def poll_instagram(self):
        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            logger.warning("Channel Instagram introuvable (id=%s)", CHANNEL_ID)
            return

        data = _load_data()
        is_first_run = not data.get("sent_shortcodes")
        fetch_count = BACKFILL_COUNT if is_first_run else 5

        posts = await asyncio.get_event_loop().run_in_executor(None, _fetch_posts, fetch_count)
        if not posts:
            return

        posts_to_send = list(reversed(posts))
        sent_before = len(data.get("sent_shortcodes", []))
        await self._send_posts(channel, posts_to_send, data)
        sent_after = len(data.get("sent_shortcodes", []))
        new_count = sent_after - sent_before
        if new_count:
            logger.info("Instagram: %d nouveau(x) post(s) envoyés", new_count)

    @poll_instagram.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="instagram_sync", description="[Admin] Synchronise les derniers posts Instagram")
    @app_commands.default_permissions(administrator=True)
    async def instagram_sync(self, interaction: discord.Interaction, nombre: int = BACKFILL_COUNT):
        await interaction.response.defer(ephemeral=True)
        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            await interaction.followup.send("❌ Channel Instagram introuvable.", ephemeral=True)
            return

        posts = await asyncio.get_event_loop().run_in_executor(None, _fetch_posts, nombre)
        if not posts:
            await interaction.followup.send("❌ Impossible de récupérer les posts Instagram.", ephemeral=True)
            return

        data = _load_data()
        sent_before = len(data.get("sent_shortcodes", []))
        await self._send_posts(channel, list(reversed(posts)), data)
        sent_after = len(data.get("sent_shortcodes", []))
        new_count = sent_after - sent_before
        await interaction.followup.send(
            f"✅ {new_count} nouveau(x) post(s) envoyé(s) sur {nombre} récupérés.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Instagram(bot))
