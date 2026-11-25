import logging
import os
import json
import asyncio
import datetime
import instaloader
import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("r2d12.instagram")

DATA_FILE = "data/instagram.json"
INSTAGRAM_USERNAME = "paramourduspin_"
CHANNEL_ID = 1575170929544270046
POLL_INTERVAL_MINUTES = 15
BACKFILL_COUNT = 10

# Credentials for authenticated scraping (required since Instagram blocked anon access)
IG_LOGIN = os.getenv("INSTAGRAM_LOGIN")
IG_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
# Path to instaloader session file (alternative to password)
IG_SESSION_FILE = os.getenv("INSTAGRAM_SESSION_FILE", "data/ig_session")
IG_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "data/ig_cookies.txt")


def _load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sent_shortcodes": []}


def _save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _make_loader() -> instaloader.Instaloader:
    from http.cookiejar import MozillaCookieJar
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        quiet=True,
    )
    # 1. Try instaloader session file
    if os.path.exists(IG_SESSION_FILE):
        try:
            loader.load_session_from_file(IG_LOGIN or INSTAGRAM_USERNAME, IG_SESSION_FILE)
            logger.info("Instagram: session chargée depuis %s", IG_SESSION_FILE)
            return loader
        except Exception as e:
            logger.warning("Instagram: échec chargement session: %s", e)
    # 2. Try browser cookies file (Netscape format exported from Chrome)
    if os.path.exists(IG_COOKIES_FILE):
        try:
            jar = MozillaCookieJar()
            jar.load(IG_COOKIES_FILE, ignore_discard=True, ignore_expires=True)
            loader.context._session.cookies.update(jar)
            logger.info("Instagram: cookies chargés depuis %s", IG_COOKIES_FILE)
            return loader
        except Exception as e:
            logger.warning("Instagram: échec chargement cookies: %s", e)
    # 3. Fall back to password login
    if IG_LOGIN and IG_PASSWORD:
        try:
            loader.login(IG_LOGIN, IG_PASSWORD)
            os.makedirs("data", exist_ok=True)
            loader.save_session_to_file(IG_SESSION_FILE)
            logger.info("Instagram: connecté en tant que %s, session sauvegardée", IG_LOGIN)
        except Exception as e:
            logger.error("Instagram: échec login: %s", e)
    else:
        logger.warning("Instagram: aucun authentification configurée")
    return loader


def _fetch_posts(count: int) -> list[dict]:
    """Fetch the most recent `count` posts from the profile (blocking)."""
    loader = _make_loader()
    try:
        profile = instaloader.Profile.from_username(loader.context, INSTAGRAM_USERNAME)
    except instaloader.exceptions.ProfileNotExistsException:
        logger.error("Profil Instagram introuvable: %s", INSTAGRAM_USERNAME)
        return []
    except Exception as e:
        logger.error("Erreur chargement profil Instagram: %s", e)
        return []

    posts = []
    try:
        for post in profile.get_posts():
            posts.append({
                "shortcode": post.shortcode,
                "url": f"https://www.instagram.com/p/{post.shortcode}/",
                "caption": post.caption or "",
                "image_url": post.url,
                "timestamp": post.date_utc.isoformat(),
                "is_video": post.is_video,
                "typename": post.typename,
            })
            if len(posts) >= count:
                break
    except Exception as e:
        logger.error("Erreur récupération posts Instagram: %s", e)

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
        """Send posts to channel and update data. posts should be oldest-first."""
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
                # Small delay to avoid rate limits
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
        posts = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_posts, fetch_count
        )
        if not posts:
            return

        # posts from instaloader are newest-first → reverse for chronological send
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

    # Admin command to manually trigger a backfill
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
