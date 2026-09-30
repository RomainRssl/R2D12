"""
Annonce automatique des manches de tournoi (championnats du site) sur Discord,
en fonction du mode de révélation choisi par le créateur du tournoi.

Principe : le site (Pads-Website) calcule déjà, côté serveur, si une manche
doit être visible ou non (règle identique quel que soit le mode — IMMEDIAT,
DELAI, CLOTURE_PRECEDENTE, MANUEL). Ce cog ne réimplémente donc AUCUNE règle
de révélation : il sonde périodiquement GET /api/championnats/bot, qui renvoie
un booléen `revelee` déjà calculé par manche, et annonce toute manche qui vient
de passer à `revelee=true` qu'il n'a pas encore annoncée.

Chaque manche révélée est annoncée et traitée exactement comme une course
seule (cogs.calendar._announce_race) : création d'un rôle mentionnable et
d'un salon privé dédié sous RACES_CATEGORY_ID, annonce avec boutons
d'inscription dans RACES_CHANNEL_ID (avec l'affiche de la manche si elle a
été ajoutée), message d'info dupliqué dans le salon privé, sélection de
catégorie si le tournoi en a plusieurs au programme (réutilise
cogs.calendar.ClassRegistrationView), et rappel des identifiants serveur
5 min avant le départ (check_manche_reminders). Cela vaut pour tous
les modes de révélation, y compris IMMEDIAT : dès que le tournoi passe en
EN_COURS, toutes ses manches sont révélées d'un coup et obtiennent chacune
leur propre salon, sans traitement groupé particulier.

Déduplication : ce cog garde la trace de ce qu'il a déjà annoncé dans
data/tournois_state.json (par championnat -> manches déjà annoncées et
messages d'inscription publiés), pour ne jamais reposter deux fois la même
annonce au sondage suivant. Au tout premier lancement (fichier absent),
l'existant est marqué comme déjà annoncé sans rien poster, pour éviter une
rafale d'annonces au déploiement.

Nouveau tournoi : dès que le tournoi passe en EN_COURS (clic "Démarrer" par
le staff), une annonce de présentation — avec l'affiche du tournoi
(`imageUrl`) si elle a été ajoutée — est postée dans le salon communication
TOURNOIS_ANNONCE_CHANNEL_ID, purement informative. Elle ne dévoile rien du
calendrier : les manches restent annoncées selon le mode de révélation,
comme décrit ci-dessus.

Persistance : les boutons d'inscription (tournoi et sélection de catégorie)
sont réenregistrés au chargement du cog (bot.add_view) à partir de ce même
fichier, ils survivent donc à un redémarrage du bot.

Nettoyage : chaque annonce de manche crée un rôle Discord (le salon, lui,
n'est jamais supprimé — comme pour une course seule). Ce rôle est supprimé
(et les boutons retirés du message) 24 h après la manche concernée, ou dès
que le tournoi n'est plus en PREPARATION / EN_COURS, pour ne pas accumuler de
rôles (limite Discord : 250).

Sécurité : un tournoi qui disparaît de la réponse de l'API n'est considéré
comme terminé qu'après plusieurs sondages consécutifs sans lui, et jamais sur
une réponse entièrement vide (probable erreur côté site). Dans ces cas-là, seul
le nettoyage à 24 h après la manche s'applique, ce qui évite de supprimer
toutes les inscriptions sur une simple réponse erronée.
"""

import os
import json
import logging
import aiohttp
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks

from .calendar import (
    ClassRegistrationView,
    _build_class_embeds,
    _load_registrations,
    _save_registrations,
    _slugify,
)

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
RACES_CATEGORY_ID = int(os.getenv("RACES_CATEGORY_ID", "1399427481945247817"))
TOURNOIS_ANNONCE_CHANNEL_ID = int(os.getenv("TOURNOIS_ANNONCE_CHANNEL_ID", "1505318885673664594"))
RACES_STAFF_ROLE_ID = int(os.getenv("RACES_STAFF_ROLE_ID", "1424791316881211412"))
RACES_NOTIFY_ROLE_ID = int(os.getenv("RACES_NOTIFY_ROLE_ID", "1505321380420255784"))

DATA_STATE = "data/tournois_state.json"
PARIS = ZoneInfo("Europe/Paris")
EMBED_COLOR = 0xF07000
STATUTS_ACTIFS = {"PREPARATION", "EN_COURS"}
DUREE_ROLE_APRES_MANCHE = timedelta(hours=24)
# Nombre de sondages consécutifs (5 min chacun) sans un tournoi dans l'API
# avant de le considérer comme terminé.
ABSENCES_AVANT_NETTOYAGE = 6

MODES_LABELS = {
    "IMMEDIAT": "Tout révélé dès le lancement",
    "DELAI": "Révélation à délai fixe avant chaque manche",
    "CLOTURE_PRECEDENTE": "Révélation à la clôture de la manche précédente",
    "MANUEL": "Révélation manuelle par le staff",
}


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _load_state() -> dict | None:
    """Etat persisté, ou None si le fichier n'existe pas encore (premier lancement)."""
    try:
        with open(DATA_STATE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _parse_iso(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _save_state(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_STATE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _format_date_heure(iso: str) -> tuple[str, str]:
    """Retourne (date FR, heure HH:MM) à partir d'un ISO renvoyé par le site."""
    dt = _parse_iso(iso).astimezone(PARIS)
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

async def _fetch_reputation(discord_id: str) -> int | None:
    """Réputation actuelle d'un pilote (0-200) d'après son ID Discord, ou None
    si le pilote n'a pas de profil sur le site (jamais connecté)."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{SITE_URL}/api/players/by-discord",
                params={"discordIds": discord_id},
                headers={"x-bot-secret": BOT_API_SECRET},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    logger.error("API by-discord — statut %s", r.status)
                    return None
                data = await r.json()
                if not data:
                    return None
                return data[0].get("reputation")
    except Exception as e:
        logger.error("Erreur API by-discord (réputation) : %s", e)
        return None


class TournoiButton(discord.ui.Button):
    def __init__(self, role_id: int, reputation_min: int | None = None):
        super().__init__(
            label="S'inscrire",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"tournoi_register_{role_id}",
        )
        self.role_id = role_id
        self.reputation_min = reputation_min

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

        if self.reputation_min is not None:
            await interaction.response.defer(ephemeral=True)
            reputation = await _fetch_reputation(str(interaction.user.id))
            if reputation is None:
                await interaction.followup.send(
                    "❌ Inscription refusée : votre profil n'a pas été trouvé sur le site "
                    f"({SITE_URL}). Connectez-vous-y au moins une fois via Discord, puis réessayez.",
                    ephemeral=True,
                )
                return
            if reputation < self.reputation_min:
                await interaction.followup.send(
                    f"❌ Inscription refusée : ce tournoi requiert une réputation minimum de "
                    f"**{self.reputation_min}/200**, la vôtre est de **{reputation}/200**.",
                    ephemeral=True,
                )
                return
            await interaction.user.add_roles(role)
            await interaction.followup.send(f"✅ Inscrit pour **{role.name}** !", ephemeral=True)
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
    def __init__(self, role_id: int, reputation_min: int | None = None):
        super().__init__(timeout=None)
        self.add_item(TournoiButton(role_id, reputation_min))
        self.add_item(TournoiUnregisterButton(role_id))


# ── Cog ──────────────────────────────────────────────────────────────────────

def _new_entry() -> dict:
    return {
        "statut_connu": None,
        "nouveau_annonce": False,
        "manches_annoncees": [],
        # message_id -> {channel_id, role_id, reputation_min, expire_at,
        # server_name, server_password, date, notified_5min}
        "annonces": {},
    }


def _expiration(dates: list) -> str | None:
    """Date (ISO UTC) à laquelle le rôle d'une annonce peut être supprimé :
    24 h après la plus tardive des manches concernées, ou None si aucune date."""
    parsed = [_parse_iso(d) for d in dates if d]
    if not parsed:
        return None
    return (max(parsed) + DUREE_ROLE_APRES_MANCHE).astimezone(timezone.utc).isoformat()


class Tournois(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_tournois_loop.start()
        self.check_manche_reminders.start()

    async def cog_load(self):
        # Réenregistre les boutons d'inscription des annonces encore actives,
        # sinon ils ne répondent plus après un redémarrage du bot. Les vues de
        # sélection de catégorie (data/race_registrations.json, partagé avec
        # cogs.calendar) sont, elles, déjà restaurées par le on_ready de ce
        # dernier — pas besoin de le refaire ici.
        for entry in (_load_state() or {}).values():
            for msg_id, annonce in entry.get("annonces", {}).items():
                view = TournoiRegistrationView(annonce["role_id"], annonce.get("reputation_min"))
                self.bot.add_view(view, message_id=int(msg_id))

    def cog_unload(self):
        self.check_tournois_loop.cancel()
        self.check_manche_reminders.cancel()

    # ── Appel API site ────────────────────────────────────────────────────

    async def _fetch_championnats(self) -> list | None:
        """Liste des championnats, ou None en cas d'erreur (à distinguer d'une
        liste vide, qui signifie qu'aucun tournoi n'est actif)."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{SITE_URL}/api/championnats/bot",
                    headers={"x-bot-secret": BOT_API_SECRET},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        logger.error("API /api/championnats/bot — statut %s", r.status)
                        return None
                    data = await r.json()
                    return data if isinstance(data, list) else None
        except Exception as e:
            logger.error("Erreur API /api/championnats/bot : %s", e)
            return None

    # ── Construction des embeds ──────────────────────────────────────────

    def _build_manche_embed(self, champ: dict, manche: dict, manche_channel=None) -> discord.Embed:
        titre = champ["nom"] + (f" — {champ['theme']}" if champ.get("theme") else "")
        embed = discord.Embed(
            title=f"🏁 {titre} — Manche {manche['ordre']}",
            color=EMBED_COLOR,
        )
        circuit = manche.get("circuitCourt") or manche.get("circuit") or f"Circuit mystère (manche {manche['ordre']})"
        embed.add_field(name="Circuit", value=circuit, inline=True)
        if manche.get("date"):
            date_str, heure_str = _format_date_heure(manche["date"])
            embed.add_field(name="Date", value=date_str.capitalize(), inline=True)
            embed.add_field(name="Heure", value=f"{heure_str} (heure de Paris)", inline=True)
        # Catégories du tournoi (figées au démarrage, identiques pour toutes
        # les manches) — indicatives pour les pilotes.
        categories = champ.get("categories") or []
        if categories:
            embed.add_field(name="Catégories", value=", ".join(categories), inline=False)
        if manche_channel:
            embed.add_field(name="💬 Salon", value=manche_channel.mention, inline=False)

        extras = [l for l in (_reputation_ligne(champ), _mode_equipe_ligne(champ)) if l]
        if extras:
            embed.add_field(name="\u200b", value="\n\n".join(extras), inline=False)

        embed.set_footer(text="Par amour du spin — inscrivez-vous ci-dessous")

        image_url = manche.get("imageUrl")
        if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
            embed.set_image(url=image_url)

        return embed

    def _build_nouveau_embed(self, champ: dict) -> discord.Embed:
        titre = champ["nom"] + (f" — {champ['theme']}" if champ.get("theme") else "")
        nb_manches = len(champ["manches"])
        lignes = [
            f"🎯 **{champ['nbCoursesComptees']}** course(s) comptée(s) sur "
            f"**{nb_manches}** course(s) au total.",
        ]
        mode = MODES_LABELS.get(champ.get("modeRevelation"))
        if mode:
            lignes.append(f"🔎 {mode}")
        lignes += [l for l in (_reputation_ligne(champ), _mode_equipe_ligne(champ)) if l]
        embed = discord.Embed(
            title=f"🆕 Nouveau tournoi : {titre}",
            url=f"{SITE_URL}/tournois/{champ['id']}",
            description="\n\n".join(lignes),
            color=EMBED_COLOR,
        )
        image_url = champ.get("imageUrl")
        if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
            embed.set_image(url=image_url)
        embed.set_footer(text="Par amour du spin")
        return embed

    # ── Annonce ──────────────────────────────────────────────────────────

    async def _announce_nouveau(self, champ: dict) -> None:
        channel = await self.bot.fetch_channel(TOURNOIS_ANNONCE_CHANNEL_ID)
        await channel.send(embed=self._build_nouveau_embed(champ))

        notify_role = channel.guild.get_role(RACES_NOTIFY_ROLE_ID)
        if notify_role:
            try:
                await channel.send(notify_role.mention)
            except Exception as e:
                logger.warning("Ping du rôle de notification impossible : %s", e)

    async def _announce_manche(self, entry: dict, champ: dict, manche: dict) -> discord.Message:
        """Traite une manche exactement comme une course seule
        (cogs.calendar._announce_race) : rôle + salon privé dédié, annonce
        avec boutons dans RACES_CHANNEL_ID, message d'info dupliqué dans le
        salon, sélection de catégorie si plusieurs sont au programme du
        tournoi. Enregistre l'annonce dans `entry["annonces"]` (persistance
        des boutons, nettoyage, rappel serveur)."""
        channel = await self.bot.fetch_channel(RACES_CHANNEL_ID)
        guild = channel.guild
        reputation_min = champ.get("reputationMin")

        role_base = manche.get("nomSalon") or f"{champ['nom']} — Manche {manche['ordre']}"
        role = await guild.create_role(name=role_base[:100], mentionable=True)

        category = guild.get_channel(RACES_CATEGORY_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
            role: discord.PermissionOverwrite(
                view_channel=True, send_messages=False, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        staff_role = guild.get_role(RACES_STAFF_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        slug_base = manche.get("nomSalon") or f"{champ['nom']}-manche-{manche['ordre']}"
        try:
            manche_channel = await guild.create_text_channel(
                name=_slugify(slug_base),
                category=category,
                overwrites=overwrites,
            )
        except Exception:
            await role.delete(reason="Échec de la création du salon de manche")
            raise

        try:
            view = TournoiRegistrationView(role.id, reputation_min)
            msg = await channel.send(
                embed=self._build_manche_embed(champ, manche, manche_channel), view=view
            )
        except Exception:
            # Pas de salon/rôle orphelin si l'envoi échoue
            await manche_channel.delete(reason="Échec de l'annonce de manche")
            await role.delete(reason="Échec de l'annonce de manche")
            raise

        # Enregistrée dès que l'annonce est postée : si une étape suivante
        # échoue, la manche n'est pas réannoncée (rôle + salon + annonce en
        # double à chaque sondage) et le rôle reste nettoyé à l'expiration.
        entry["annonces"][str(msg.id)] = {
            "channel_id": channel.id,
            "manche_channel_id": manche_channel.id,
            "role_id": role.id,
            "reputation_min": reputation_min,
            "expire_at": _expiration([manche.get("date")]),
            "server_name": manche.get("serverName") or "",
            "server_password": manche.get("serverPassword") or "",
            "date": manche.get("date"),
            "notified_5min": False,
        }

        notify_role = guild.get_role(RACES_NOTIFY_ROLE_ID)
        if notify_role:
            try:
                await channel.send(notify_role.mention)
            except Exception as e:
                logger.warning("Ping du rôle de notification impossible : %s", e)

        try:
            # Message d'info dans le salon privé (sans bouton, comme pour une course)
            await manche_channel.send(embed=self._build_manche_embed(champ, manche))

            # Sélection de catégorie dans le salon privé, si le tournoi en propose
            # plusieurs — réutilise le même système que les courses multiclasses.
            categories = [c for c in (champ.get("categories") or []) if c][:5]
            if len(categories) >= 2:
                classes_data = {c: [] for c in categories}
                cls_view = ClassRegistrationView(categories, manche_channel.id)
                cls_msg = await manche_channel.send(
                    embeds=_build_class_embeds(role_base, classes_data), view=cls_view
                )
                regs = _load_registrations()
                regs[str(manche_channel.id)] = {
                    "title": role_base,
                    "message_id": str(cls_msg.id),
                    "classes": classes_data,
                    "classes_max": None,
                }
                _save_registrations(regs)
        except Exception as e:
            logger.error(
                "Manche %s annoncée, mais préparation du salon %s incomplète : %s",
                manche.get("id"), manche_channel.id, e,
            )

        return msg

    async def _cleanup_annonce(self, msg_id: str, annonce: dict) -> None:
        """Supprime le rôle d'une annonce et retire ses boutons du message."""
        try:
            channel = await self.bot.fetch_channel(annonce["channel_id"])
        except discord.NotFound:
            return
        role = channel.guild.get_role(annonce["role_id"])
        if role:
            try:
                await role.delete(reason="Manche/tournoi terminé")
            except discord.NotFound:
                pass
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(view=None)
        except discord.NotFound:
            pass

    async def _cleanup_entry(self, entry: dict, tout: bool) -> bool:
        """Nettoie les annonces expirées (ou toutes si `tout`). Renvoie True si
        l'état a changé."""
        now = datetime.now(timezone.utc)
        changed = False
        for msg_id, annonce in list(entry.get("annonces", {}).items()):
            expire_at = annonce.get("expire_at")
            if not tout and (not expire_at or _parse_iso(expire_at) > now):
                continue
            try:
                await self._cleanup_annonce(msg_id, annonce)
            except Exception as e:
                logger.error("Échec nettoyage annonce tournoi %s : %s", msg_id, e)
                continue
            del entry["annonces"][msg_id]
            changed = True
        return changed

    # ── Boucle de sondage ─────────────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def check_tournois_loop(self):
        if not RACES_CHANNEL_ID or not BOT_API_SECRET:
            return

        championnats = await self._fetch_championnats()
        if championnats is None:
            return

        state = _load_state()
        premier_lancement = state is None
        if premier_lancement:
            state = {}
        changed = premier_lancement

        ids_termines = set()
        for champ in championnats:
            cid = str(champ["id"])
            if champ.get("statut") not in STATUTS_ACTIFS:
                ids_termines.add(cid)
            entry = state.setdefault(cid, _new_entry())
            entry.setdefault("annonces", {})
            # Tournoi déjà suivi avant l'ajout de cette annonce : considéré
            # comme déjà présenté (pas de rafale au déploiement).
            entry.setdefault("nouveau_annonce", True)
            if entry.get("absences"):
                entry["absences"] = 0
                changed = True

            if entry["statut_connu"] != champ.get("statut"):
                entry["statut_connu"] = champ.get("statut")
                changed = True

            if champ.get("statut") not in STATUTS_ACTIFS:
                continue

            # Annonce "nouveau tournoi" (avec affiche) : seulement une fois le
            # tournoi démarré (clic "Démarrer" -> EN_COURS), jamais en
            # PREPARATION, même si ses manches peuvent déjà être révélées côté
            # site en mode IMMEDIAT.
            if not entry["nouveau_annonce"] and champ.get("statut") == "EN_COURS":
                if premier_lancement or not TOURNOIS_ANNONCE_CHANNEL_ID:
                    entry["nouveau_annonce"] = True
                else:
                    try:
                        await self._announce_nouveau(champ)
                        entry["nouveau_annonce"] = True
                        changed = True
                    except Exception as e:
                        logger.error("Échec annonce nouveau tournoi %s : %s", cid, e)

            # Une annonce par manche, dès qu'elle passe à revelee=true (peu
            # importe le mode de révélation — le site a déjà tranché). En
            # IMMEDIAT, toutes les manches passent à revelee=true d'un coup au
            # démarrage : elles sont alors toutes annoncées ici, chacune avec
            # son propre salon, sans traitement groupé particulier.
            for manche in champ["manches"]:
                if not manche["revelee"]:
                    continue
                if manche["id"] in entry["manches_annoncees"]:
                    continue
                if premier_lancement:
                    entry["manches_annoncees"].append(manche["id"])
                    continue
                try:
                    await self._announce_manche(entry, champ, manche)
                    entry["manches_annoncees"].append(manche["id"])
                    changed = True
                except Exception as e:
                    logger.error(
                        "Échec annonce manche %s (tournoi %s) : %s", manche["id"], cid, e
                    )

        # Tournois absents de la réponse : on ne les considère terminés
        # qu'après ABSENCES_AVANT_NETTOYAGE sondages consécutifs, et une
        # réponse entièrement vide ne compte pas (probable erreur du site).
        ids_presents = {str(c["id"]) for c in championnats}
        if championnats:
            for cid, entry in state.items():
                if cid in ids_presents or not entry.get("annonces"):
                    continue
                entry["absences"] = entry.get("absences", 0) + 1
                changed = True
                if entry["absences"] >= ABSENCES_AVANT_NETTOYAGE:
                    ids_termines.add(cid)
                else:
                    logger.warning(
                        "Tournoi %s absent de l'API (%s/%s)",
                        cid, entry["absences"], ABSENCES_AVANT_NETTOYAGE,
                    )

        # Nettoyage des rôles : annonces expirées (24 h après la manche), ou
        # toutes les annonces d'un tournoi terminé.
        for cid, entry in state.items():
            if await self._cleanup_entry(entry, tout=cid in ids_termines):
                changed = True

        if changed:
            _save_state(state)

    @check_tournois_loop.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── Rappel 5 min avant la manche ──────────────────────────────────────

    @tasks.loop(minutes=1)
    async def check_manche_reminders(self):
        """Envoie les identifiants serveur dans le salon de manche 5 min avant
        le départ — même principe que cogs.calendar.check_race_reminders."""
        now = datetime.now(PARIS)
        state = _load_state()
        if not state:
            return
        changed = False

        for entry in state.values():
            for msg_id, annonce in entry.get("annonces", {}).items():
                if annonce.get("notified_5min"):
                    continue
                if not annonce.get("date") or not annonce.get("manche_channel_id"):
                    continue
                if not annonce.get("server_name") and not annonce.get("server_password"):
                    continue
                try:
                    manche_dt = _parse_iso(annonce["date"]).astimezone(PARIS)
                except ValueError:
                    continue

                delta = manche_dt - now
                if not (timedelta(minutes=4) <= delta <= timedelta(minutes=6)):
                    continue

                try:
                    manche_channel = await self.bot.fetch_channel(int(annonce["manche_channel_id"]))
                except Exception as e:
                    logger.warning(
                        "Rappel 5min tournoi — salon introuvable (%s) : %s",
                        annonce["manche_channel_id"], e,
                    )
                    annonce["notified_5min"] = True
                    changed = True
                    continue

                embed = discord.Embed(title="🚦 Départ dans 5 minutes", color=0xE63946)
                if annonce.get("server_name"):
                    embed.add_field(name="🖥️ Nom du serveur", value=annonce["server_name"], inline=False)
                if annonce.get("server_password"):
                    embed.add_field(name="🔒 Mot de passe", value=annonce["server_password"], inline=False)
                embed.set_footer(text="Par amour du spin · Bonne course ! 🏎️")

                try:
                    await manche_channel.send(embed=embed)
                    logger.info("Rappel 5min tournoi envoyé dans %s", manche_channel.id)
                except Exception as e:
                    logger.error(
                        "Rappel 5min tournoi — envoi impossible dans %s : %s",
                        annonce["manche_channel_id"], e,
                    )

                annonce["notified_5min"] = True
                changed = True

        if changed:
            _save_state(state)

    @check_manche_reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tournois(bot))
