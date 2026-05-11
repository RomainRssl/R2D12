"""
credits_admin.py — Gestion des Crédits pilotes PADS (staff uniquement)

Flow :
  /gestion-credits <pilote>   (autocomplete sur les noms du site)
    → Affiche le solde actuel (scraping fiche pilote)
    → Boutons ➕ Ajouter / ➖ Retirer
    → Modal : montant + raison
    → PATCH https://paramourduspin.fun/api/admin/players/money
    → Embed de confirmation

Variables .env requises :
  RACES_SITE_URL=https://paramourduspin.fun   (déjà présent)
  BOT_API_SECRET=le_meme_secret_que_dans_env_local_du_site
"""

import logging
import re
import urllib.parse
from datetime import datetime, timedelta

import aiohttp
import discord
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands
import os

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "")

STAFF_ROLE_ID = 1424791316881211412


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _abbreviate_name(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[0][0]} {' '.join(parts[1:])}"
    return name


def _parse_credits(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    for box in soup.find_all(
        "div",
        class_=lambda c: c and "rounded-xl" in c and "p-3" in c and "border" in c,
    ):
        label_el = box.find("p", class_=lambda c: c and "uppercase" in c)
        value_el = box.find("p", class_=lambda c: c and "text-xl" in c)
        if label_el and value_el:
            if label_el.get_text(strip=True) == "ARGENT":
                raw = value_el.get_text(strip=True)
                digits = re.sub(r"\D", "", raw)
                if digits:
                    return int(digits)
    return None


# ──────────────────────────────────────────────────────────────
# Check staff
# ──────────────────────────────────────────────────────────────

def is_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande n'est disponible que sur un serveur.", ephemeral=True
            )
            return False
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if staff_role is None or staff_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)


# ──────────────────────────────────────────────────────────────
# Étape 2 — Boutons Ajouter / Retirer
# ──────────────────────────────────────────────────────────────

class OperationView(discord.ui.View):
    def __init__(self, pilot_name: str, current_credits: int):
        super().__init__(timeout=120)
        self.pilot_name = pilot_name
        self.current_credits = current_credits

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AmountModal(self.pilot_name, self.current_credits, operation="ajouter")
        )

    @discord.ui.button(label="➖ Retirer", style=discord.ButtonStyle.danger)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AmountModal(self.pilot_name, self.current_credits, operation="retirer")
        )


# ──────────────────────────────────────────────────────────────
# Étape 3 — Modal saisie montant
# ──────────────────────────────────────────────────────────────

class AmountModal(discord.ui.Modal):
    def __init__(self, pilot_name: str, current_credits: int, operation: str):
        label_op = "ajouter" if operation == "ajouter" else "retirer"
        super().__init__(title=f"Montant à {label_op} — {_abbreviate_name(pilot_name)}")
        self.pilot_name = pilot_name
        self.current_credits = current_credits
        self.operation = operation

        self.amount_input = discord.ui.TextInput(
            label="Montant (en Crédits)",
            placeholder="Ex : 5000",
            min_length=1,
            max_length=10,
            required=True,
        )
        self.reason_input = discord.ui.TextInput(
            label="Raison (optionnel)",
            placeholder="Ex : Victoire course #3",
            required=False,
            max_length=200,
        )
        self.add_item(self.amount_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(re.sub(r"\s", "", self.amount_input.value.strip()))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Le montant doit être un nombre entier positif (ex : `5000`).",
                ephemeral=True,
            )
            return

        reason = self.reason_input.value.strip() or None
        delta = amount if self.operation == "ajouter" else -amount

        # ── Appel API site ──────────────────────────────────────
        api_url = f"{SITE_URL}/api/admin/players/money"
        payload = {"username": self.pilot_name, "delta": delta, "reason": reason}
        headers = {"Authorization": f"Bearer {BOT_API_SECRET}"}

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.patch(
                    api_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()

                    if resp.status == 422:
                        await interaction.response.send_message(
                            f"❌ {data.get('error', 'Solde insuffisant.')}", ephemeral=True
                        )
                        return
                    if resp.status == 404:
                        await interaction.response.send_message(
                            f"❌ Pilote **{self.pilot_name}** introuvable en base.", ephemeral=True
                        )
                        return
                    if resp.status != 200:
                        await interaction.response.send_message(
                            f"❌ Erreur serveur ({resp.status}) : {data.get('error', 'inconnu')}",
                            ephemeral=True,
                        )
                        return

        except aiohttp.ClientError as e:
            await interaction.response.send_message(
                f"❌ Impossible de contacter le site : `{e}`", ephemeral=True
            )
            return

        # ── Embed de confirmation ───────────────────────────────
        new_balance = data["newBalance"]
        old_balance = data["oldBalance"]
        op_label = f"+{amount:,}" if self.operation == "ajouter" else f"-{amount:,}"
        color = discord.Color.green() if self.operation == "ajouter" else discord.Color.red()
        emoji = "➕" if self.operation == "ajouter" else "➖"
        pilot_url = f"{SITE_URL}/pilotes/{urllib.parse.quote(self.pilot_name)}"

        embed = discord.Embed(title=f"💰 Crédits modifiés {emoji}", color=color)
        embed.add_field(
            name="Pilote",
            value=f"[{_abbreviate_name(self.pilot_name)}]({pilot_url})",
            inline=True,
        )
        embed.add_field(name="Opération", value=f"**{op_label} Crédits**", inline=True)
        embed.add_field(name="Nouveau solde", value=f"**{new_balance:,} Crédits**", inline=True)
        embed.add_field(name="Ancien solde", value=f"{old_balance:,} Crédits", inline=True)
        embed.add_field(name="Raison", value=reason or "Aucune raison précisée", inline=False)
        embed.set_footer(
            text=f"Effectué par {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.response.edit_message(embed=embed, view=None)


# ──────────────────────────────────────────────────────────────
# Cog principal
# ──────────────────────────────────────────────────────────────

class CreditsAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: list[str] = []
        self._cache_at: datetime | None = None

    async def _fetch_pilots(self) -> list[str]:
        # Réutilise le cache de pilots.py si disponible
        pilots_cog = self.bot.cogs.get("Pilots")
        if pilots_cog:
            return await pilots_cog._fetch_pilots()

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
        except Exception as e:
            logger.error("Erreur fetch pilotes (credits_admin) : %s", e)

        return self._cache

    @app_commands.command(
        name="gestion-credits",
        description="[STAFF] Ajouter ou retirer des Crédits au solde d'un pilote.",
    )
    @app_commands.describe(pilote="Nom du pilote (tapez pour rechercher)")
    @is_staff()
    async def gestion_credits(self, interaction: discord.Interaction, pilote: str):
        await interaction.response.defer(ephemeral=True)

        url = f"{SITE_URL}/pilotes/{urllib.parse.quote(pilote)}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 404:
                        await interaction.followup.send(
                            f"❌ Pilote **{pilote}** introuvable sur le site.", ephemeral=True
                        )
                        return
                    html = await r.text()
        except Exception as e:
            await interaction.followup.send(
                f"❌ Impossible de récupérer la fiche : `{e}`", ephemeral=True
            )
            return

        current_credits = _parse_credits(html)
        if current_credits is None:
            await interaction.followup.send(
                f"❌ Impossible de lire le solde de **{_abbreviate_name(pilote)}**.",
                ephemeral=True,
            )
            return

        pilot_url = f"{SITE_URL}/pilotes/{urllib.parse.quote(pilote)}"
        embed = discord.Embed(
            title="💰 Gestion des Crédits",
            description=(
                f"**Pilote :** [{_abbreviate_name(pilote)}]({pilot_url})\n"
                f"**Solde actuel :** {current_credits:,} Crédits\n\n"
                "Choisissez l'opération à effectuer."
            ),
            color=discord.Color.blue(),
        )
        await interaction.followup.send(embed=embed, view=OperationView(pilote, current_credits), ephemeral=True)

    @gestion_credits.autocomplete("pilote")
    async def pilot_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice]:
        pilots = await self._fetch_pilots()
        matches = [
            p for p in pilots
            if current.lower() in p.lower()
            or current.lower() in _abbreviate_name(p).lower()
        ][:25]
        return [app_commands.Choice(name=_abbreviate_name(p), value=p) for p in matches]


async def setup(bot: commands.Bot):
    await bot.add_cog(CreditsAdmin(bot))
