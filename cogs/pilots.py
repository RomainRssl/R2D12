import logging
import urllib.parse
from datetime import datetime, timedelta

import aiohttp
import discord
from bs4 import BeautifulSoup
from discord.ext import commands

import os

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")

TIER_ICONS = {
    "platinum": "💎",
    "gold":     "🥇",
    "silver":   "🥈",
    "bronze":   "🥉",
}


def _tier_icon(tier: str) -> str:
    for key, icon in TIER_ICONS.items():
        if key in tier.lower():
            return icon
    return "🏅"


class Pilots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cache: list[str] = []
        self._cache_at: datetime | None = None

    # ── Cache pilotes ─────────────────────────────────────────────

    async def _fetch_pilots(self) -> list[str]:
        """Retourne la liste des noms de pilotes (cache 1 h)."""
        now = datetime.utcnow()
        if self._cache_at and (now - self._cache_at) < timedelta(hours=1):
            return self._cache

        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{SITE_URL}/pilotes", timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    html = await r.text()

            soup = BeautifulSoup(html, "html.parser")
            seen, pilots = set(), []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/pilotes/") and href != "/pilotes":
                    name = urllib.parse.unquote(href[len("/pilotes/"):])
                    if name and name not in seen:
                        seen.add(name)
                        pilots.append(name)

            self._cache = pilots
            self._cache_at = now
            logger.info("Cache pilotes mis à jour : %d pilotes", len(pilots))
        except Exception as e:
            logger.error("Erreur récupération liste pilotes : %s", e)

        return self._cache

    # ── Parsing fiche pilote ──────────────────────────────────────

    def _parse_profile(self, html: str, username: str, url: str) -> discord.Embed | None:
        soup = BeautifulSoup(html, "html.parser")

        # Nom affiché
        h1 = soup.find("h1", class_=lambda c: c and "text-3xl" in c)
        if not h1:
            return None
        display_name = h1.get_text(strip=True)

        # Rang global
        rank = ""
        for span in soup.find_all("span"):
            t = span.get_text(strip=True)
            if "au classement global" in t:
                rank = t
                break

        # Boîtes de stats (argent / réputation / courses)
        stats: dict[str, str] = {}
        for box in soup.find_all(
            "div",
            class_=lambda c: c and "rounded-xl" in c and "p-3" in c and "border" in c,
        ):
            label_el = box.find("p", class_=lambda c: c and "uppercase" in c)
            value_el = box.find("p", class_=lambda c: c and "text-xl" in c)
            if label_el and value_el:
                stats[label_el.get_text(strip=True)] = value_el.get_text(strip=True)

        # Progression par classe
        classes = []
        for card in soup.find_all(
            "div",
            class_=lambda c: c and "rounded-xl" in c and "p-4" in c and "border" in c,
        ):
            class_el = card.find("span", class_=lambda c: c and "font-mono" in c)
            if not class_el:
                continue

            class_name = class_el.get_text(strip=True)

            # Tier (Bronze / Silver…)
            tier = ""
            for span in card.find_all("span"):
                t = span.get_text(strip=True)
                if any(x in t.lower() for x in ["bronze", "silver", "gold", "platinum"]):
                    tier = t
                    break

            # XP valeur
            xp_el = card.find("p", class_=lambda c: c and "text-xl" in c)
            xp = xp_el.get_text(strip=True) if xp_el else "—"

            # Texte de progression XP (ex: "898 XP → SILVER")
            xp_next = ""
            for p in card.find_all("p", class_=lambda c: c and "text-xs" in c):
                t = p.get_text(strip=True)
                if "→" in t:
                    xp_next = t
                    break

            # Points Ladder
            ladder_pts = ""
            ladder_next = ""
            sections = card.find_all(
                "div", class_=lambda c: c and "mb-3" in c
            )
            for sec in sections:
                label_el = sec.find(
                    "span", class_=lambda c: c and "uppercase" in c
                )
                if label_el and "LADDER" in label_el.get_text():
                    pts_el = sec.find(
                        "span", class_=lambda c: c and "text-xl" in c
                    )
                    if pts_el:
                        ladder_pts = pts_el.get_text(strip=True) + " pts"
                    for p in sec.find_all("p", class_=lambda c: c and "text-xs" in c):
                        t = p.get_text(strip=True)
                        if "→" in t:
                            ladder_next = t
                            break

            classes.append(
                {
                    "class": class_name,
                    "tier": tier,
                    "xp": xp,
                    "xp_next": xp_next,
                    "ladder_pts": ladder_pts,
                    "ladder_next": ladder_next,
                }
            )

        # ── Construction embed ──────────────────────────────────────
        embed = discord.Embed(
            title=f"🏎️  {display_name}",
            url=url,
            color=0xE63946,
        )
        if rank:
            embed.description = f"🏆 **{rank}**"

        if stats.get("ARGENT"):
            embed.add_field(name="💰 Argent", value=stats["ARGENT"], inline=True)
        if stats.get("RÉPUTATION"):
            embed.add_field(name="⭐ Réputation", value=stats["RÉPUTATION"], inline=True)
        if stats.get("COURSES TERMINÉES"):
            embed.add_field(name="🏁 Courses", value=stats["COURSES TERMINÉES"], inline=True)

        if classes:
            embed.add_field(
                name="📊 Progression par classe",
                value="​",
                inline=False,
            )
            for c in classes:
                icon = _tier_icon(c["tier"])
                lines = []
                if c["xp"]:
                    lines.append(f"**XP :** {c['xp']}")
                if c["xp_next"]:
                    lines.append(f"↗️ {c['xp_next']}")
                if c["ladder_pts"]:
                    lines.append(f"**Ladder :** {c['ladder_pts']}")
                if c["ladder_next"]:
                    lines.append(f"↗️ {c['ladder_next']}")
                embed.add_field(
                    name=f"{icon} {c['class']}  ·  {c['tier']}",
                    value="\n".join(lines) or "—",
                    inline=True,
                )

        embed.set_footer(text="Par amour du spin · paramourduspin.fun")
        return embed

    # ── Commande ──────────────────────────────────────────────────

    @discord.app_commands.command(
        name="fichepilote",
        description="Affiche la fiche d'un pilote du serveur",
    )
    @discord.app_commands.describe(pilote="Nom du pilote (tapez pour rechercher)")
    async def fiche_pilote(self, interaction: discord.Interaction, pilote: str):
        await interaction.response.defer()

        url = f"{SITE_URL}/pilotes/{urllib.parse.quote(pilote)}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 404:
                        await interaction.followup.send(
                            f"❌ Pilote **{pilote}** introuvable sur le site.",
                            ephemeral=True,
                        )
                        return
                    html = await r.text()
        except Exception as e:
            await interaction.followup.send(
                f"❌ Erreur lors de la récupération : {e}", ephemeral=True
            )
            return

        embed = self._parse_profile(html, pilote, url)
        if embed is None:
            await interaction.followup.send(
                f"❌ Impossible de lire la fiche de **{pilote}**.", ephemeral=True
            )
            return

        await interaction.followup.send(embed=embed)

    @fiche_pilote.autocomplete("pilote")
    async def pilot_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice]:
        pilots = await self._fetch_pilots()
        matches = [p for p in pilots if current.lower() in p.lower()][:25]
        return [discord.app_commands.Choice(name=p, value=p) for p in matches]


async def setup(bot):
    await bot.add_cog(Pilots(bot))
