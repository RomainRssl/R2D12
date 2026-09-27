"""
Annonce automatique des manches de tournoi (championnats du site) sur Discord,
en fonction du mode de révélation choisi par le créateur du tournoi.

Principe : le site (Pads-Website) calcule déjà, côté serveur, si une manche
doit être visible ou non (règle identique quel que soit le mode — IMMEDIAT,
DELAI, CLOTURE_PRECEDENTE, MANUEL). Ce cog ne réimplémente donc AUCUNE règle
de révélation : il sonde périodiquement GET /api/championnats/bot, qui renvoie
un booléen `revelee` déjà calculé par manche, et annonce toute manche qui vient
de passer à `revelee=true` qu'il n'a pas encore annoncée.

Exception : le mode IMMEDIAT est un cas particulier voulu par le staff — le
site révèle tout le calendrier dès la création du tournoi (même en
PREPARATION), mais l'annonce Discord, elle, doit attendre que l'admin clique
sur "Démarrer" (passage à EN_COURS). Ce cog gère donc ce cas à part : il ne
déclenche l'annonce globale IMMEDIAT qu'au moment où il détecte la transition
PREPARATION -> EN_COURS, jamais avant.

Déduplication : ce cog garde la trace de ce qu'il a déjà annoncé dans
data/tournois_state.json (par championnat -> set de manches déjà annoncées,
+ un flag pour l'annonce globale IMMEDIAT), pour ne jamais reposter deux fois
la même annonce au sondage suivant.
"""

import os
import json
import logging
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
RACES_STAFF_ROLE_ID = int(os.getenv("RACES_STAFF_ROLE_ID", "1424791316881211412"))
RACES_NOTIFY_ROLE_ID = int(os.getenv("RACES_NOTIFY_ROLE_ID", "1505321380420255784"))

DATA_STATE = "data/tournois_state.json"
PARIS = ZoneInfo("Europe/Paris")
EMBED_COLOR = 0xF07000

MODES_LABELS = {
    "IMMEDIAT": "Tout révélé dès le lancement",
    "DELAI": "Révélation à délai fixe avant chaque manche",
    "CLOTURE_PRECEDENTE": "Révélation à la clôture de la manche précédente",
    "MANUEL": "Révélation manuelle par le staff",
}


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        with open(DATA_STATE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_state(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_STATE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _format_date_heure(iso: str) -> tuple[str, str]:
    """Retourne (date FR, heure HH:MM) à partir d'un ISO renvoyé par le site."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PARIS)
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    date_str = f"{jours[dt.weekday()]} {dt.day} {mois[dt.month - 1]}"
    heure_str = dt.strftime("%H:%M")
    return date_str, heure_str


def _mode_equipe_ligne(champ: dict) -> str | None:
    """Ligne à ajouter dans l'embed si le tournoi est en mode équipe."""
    if not champ.get("modeEquipe"):
        return None
    if champ.get("equipesLibres"):
        taille = "libre (aucune taille imposée)"
    else:
        taille = f"{champ.get('tailleEquipe')} pilotes par équipe"
    return (
        f"👥 **Tournoi en équipe** ({taille})\n"
        f"⚠️ Merci de préciser le nom de votre équipe en ouvrant un **ticket** auprès du staff."
    )


def _reputation_ligne(champ: dict) -> str | None:
    seuil = champ.get("reputationMin")
    if seuil is None:
        return None
    return f"⭐ Réputation minimum requise : **{seuil}/200**"


# ── Vues d'inscription (role-based, comme cogs.calendar) ─────────────────────
# Préfixe de custom_id différent de cogs.calendar pour ne jamais entrer en
# collision avec ses vues persistantes (S'inscrire/Se désinscrire des courses
# "Autres").

class TournoiButton(discord.ui.Button):
    def __init__(self, role_id: int):
        super().__init__(
            label="S'inscrire",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"tournoi_register_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Rôle introuvable.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                f"Vous êtes déjà inscrit pour **{role.name}**.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await interaction.user.add_roles(role)
        await interaction.followup.send(f"✅ Inscrit pour **{role.name}** !", ephemeral=True)


class TournoiUnregisterButton(discord.ui.Button):
    def __init__(self, role_id: int):
        super().__init__(
            label="Se désinscrire",
            style=discord.ButtonStyle.danger,
            emoji="🚪",
            custom_id=f"tournoi_unregister_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Rôle introuvable.", ephemeral=True)
            return
        if role not in interaction.user.roles:
            await interaction.response.send_message("Vous n'êtes pas inscrit.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await interaction.user.remove_roles(role)
        await interaction.followup.send(f"❌ Désinscrit de **{role.name}**.", ephemeral=True)


class TournoiRegistrationView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.add_item(TournoiButton(role_id))
        self.add_item(TournoiUnregisterButton(role_id))


# ── Cog ──────────────────────────────────────────────────────────────────────

class Tournois(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_tournois_loop.start()

    def cog_unload(self):
        self.check_tournois_loop.cancel()

    # ── Appel API site ────────────────────────────────────────────────────

    async def _fetch_championnats(self) -> list:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{SITE_URL}/api/championnats/bot",
                    headers={"x-bot-secret": BOT_API_SECRET},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        logger.error("API /api/championnats/bot — statut %s", r.status)
                        return []
                    return await r.json()
        except Exception as e:
            logger.error("Erreur API /api/championnats/bot : %s", e)
            return []

    # ── Construction des embeds ──────────────────────────────────────────

    def _build_manche_embed(self, champ: dict, manche: dict) -> discord.Embed:
        titre = champ["nom"] + (f" — {champ['theme']}" if champ.get("theme") else "")
        embed = discord.Embed(
            title=f"🏁 {titre} — Manche {manche['ordre']}",
            color=EMBED_COLOR,
        )
        circuit = manche.get("circuit") or f"Circuit mystère (manche {manche['ordre']})"
        embed.add_field(name="Circuit", value=circuit, inline=True)
        if manche.get("date"):
            date_str, heure_str = _format_date_heure(manche["date"])
            embed.add_field(name="Date", value=date_str.capitalize(), inline=True)
            embed.add_field(name="Heure", value=f"{heure_str} (heure de Paris)", inline=True)
        categories = manche.get("categories") or []
        if categories:
            embed.add_field(name="Catégories", value=", ".join(categories), inline=False)

        extras = [l for l in (_reputation_ligne(champ), _mode_equipe_ligne(champ)) if l]
        if extras:
            embed.add_field(name="​", value="\n\n".join(extras), inline=False)

        embed.set_footer(text="Par amour du spin — inscrivez-vous ci-dessous")
        return embed

    def _build_calendrier_embed(self, champ: dict) -> discord.Embed:
        titre = champ["nom"] + (f" — {champ['theme']}" if champ.get("theme") else "")
        nb_manches = len(champ["manches"])
        nb_comptees = champ["nbCoursesComptees"]
        description = f"🎯 **{nb_comptees}** course(s) comptée(s) sur **{nb_manches}** course(s) au total."
        embed = discord.Embed(
            title=f"🏆 {titre} — Calendrier complet",
            description=description,
            color=EMBED_COLOR,
        )
        for manche in champ["manches"]:
            circuit = manche.get("circuit") or f"Circuit mystère (manche {manche['ordre']})"
            if manche.get("date"):
                date_str, heure_str = _format_date_heure(manche["date"])
                valeur = f"{circuit} — {date_str.capitalize()} à {heure_str}"
            else:
                valeur = circuit
            embed.add_field(name=f"Manche {manche['ordre']}", value=valeur, inline=False)

        extras = [l for l in (_reputation_ligne(champ), _mode_equipe_ligne(champ)) if l]
        if extras:
            embed.add_field(name="​", value="\n\n".join(extras), inline=False)

        embed.set_footer(text="Par amour du spin — inscrivez-vous ci-dessous")
        return embed

    # ── Annonce ──────────────────────────────────────────────────────────

    async def _announce(self, embed: discord.Embed, role_name: str) -> None:
        channel = await self.bot.fetch_channel(RACES_CHANNEL_ID)
        guild = channel.guild
        role = await guild.create_role(name=role_name[:100], mentionable=True)
        view = TournoiRegistrationView(role.id)
        msg = await channel.send(embed=embed, view=view)

        notify_role = guild.get_role(RACES_NOTIFY_ROLE_ID)
        if notify_role:
            await channel.send(notify_role.mention)

        return msg

    # ── Boucle de sondage ─────────────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def check_tournois_loop(self):
        if not RACES_CHANNEL_ID or not BOT_API_SECRET:
            return

        championnats = await self._fetch_championnats()
        if not championnats:
            return

        state = _load_state()
        changed = False

        for champ in championnats:
            cid = champ["id"]
            entry = state.setdefault(cid, {
                "statut_connu": None,
                "immediat_annonce": False,
                "manches_annoncees": [],
            })

            if champ["modeRevelation"] == "IMMEDIAT":
                # Cas particulier : n'annonce le calendrier complet qu'au moment
                # où le tournoi passe réellement en EN_COURS (clic "Démarrer"),
                # jamais avant — même si le site, lui, montre déjà tout dès la
                # création (règle métier demandée explicitement par le staff).
                if (
                    not entry["immediat_annonce"]
                    and entry["statut_connu"] == "PREPARATION"
                    and champ["statut"] == "EN_COURS"
                ):
                    try:
                        embed = self._build_calendrier_embed(champ)
                        await self._announce(embed, champ["nom"])
                        entry["immediat_annonce"] = True
                        entry["manches_annoncees"] = [m["id"] for m in champ["manches"]]
                        changed = True
                    except Exception as e:
                        logger.error("Échec annonce calendrier tournoi %s : %s", cid, e)
                entry["statut_connu"] = champ["statut"]
                continue

            # DELAI / CLOTURE_PRECEDENTE / MANUEL : une annonce par manche,
            # dès qu'elle passe à revelee=true (peu importe pourquoi — le
            # site a déjà tranché).
            for manche in champ["manches"]:
                if not manche["revelee"]:
                    continue
                if manche["id"] in entry["manches_annoncees"]:
                    continue
                try:
                    embed = self._build_manche_embed(champ, manche)
                    role_name = f"{champ['nom']} — Manche {manche['ordre']}"
                    await self._announce(embed, role_name)
                    entry["manches_annoncees"].append(manche["id"])
                    changed = True
                except Exception as e:
                    logger.error(
                        "Échec annonce manche %s (tournoi %s) : %s", manche["id"], cid, e
                    )
            entry["statut_connu"] = champ["statut"]

        if changed:
            _save_state(state)

    @check_tournois_loop.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tournois(bot))
