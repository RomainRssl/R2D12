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
sur "Démarrer" (passage à EN_COURS). Ce cog n'annonce donc le calendrier
complet IMMEDIAT que lorsque le tournoi est vu en EN_COURS, jamais avant.

Déduplication : ce cog garde la trace de ce qu'il a déjà annoncé dans
data/tournois_state.json (par championnat -> manches déjà annoncées, flag de
l'annonce globale IMMEDIAT, et messages d'inscription publiés), pour ne jamais
reposter deux fois la même annonce au sondage suivant. Au tout premier
lancement (fichier absent), l'existant est marqué comme déjà annoncé sans rien
poster, pour éviter une rafale d'annonces au déploiement.

Nouveau tournoi : dès qu'un tournoi apparaît dans l'API (PREPARATION ou
EN_COURS), une annonce de présentation — avec l'affiche du tournoi (`imageUrl`)
si elle a été ajoutée — est postée dans le salon TOURNOIS_ANNONCE_CHANNEL_ID.
Elle ne dévoile rien du calendrier : les manches restent annoncées selon le
mode de révélation, comme décrit ci-dessus.

Persistance : les boutons d'inscription sont réenregistrés au chargement du
cog (bot.add_view) à partir de ce même fichier, ils survivent donc à un
redémarrage du bot.

Nettoyage : chaque annonce crée un rôle Discord. Ce rôle est supprimé (et les
boutons retirés du message) 24 h après la manche concernée — la dernière pour
le calendrier IMMEDIAT — ou dès que le tournoi n'est plus en PREPARATION /
EN_COURS, pour ne pas accumuler de rôles (limite Discord : 250).

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

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
BOT_API_SECRET = os.getenv("BOT_API_SECRET", "")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
TOURNOIS_ANNONCE_CHANNEL_ID = int(os.getenv("TOURNOIS_ANNONCE_CHANNEL_ID", "1505318945761132575"))
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
        "immediat_annonce": False,
        "manches_annoncees": [],
        # message_id -> {channel_id, role_id, reputation_min, expire_at}
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

    async def cog_load(self):
        # Réenregistre les boutons d'inscription des annonces encore actives,
        # sinon ils ne répondent plus après un redémarrage du bot.
        for entry in (_load_state() or {}).values():
            for msg_id, annonce in entry.get("annonces", {}).items():
                view = TournoiRegistrationView(annonce["role_id"], annonce.get("reputation_min"))
                self.bot.add_view(view, message_id=int(msg_id))

    def cog_unload(self):
        self.check_tournois_loop.cancel()

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
            embed.add_field(name="\u200b", value="\n\n".join(extras), inline=False)

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
            embed.add_field(name="\u200b", value="\n\n".join(extras), inline=False)

        embed.set_footer(text="Par amour du spin — inscrivez-vous ci-dessous")
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

    async def _announce(
        self,
        entry: dict,
        embed: discord.Embed,
        role_name: str,
        reputation_min: int | None,
        expire_at: str | None,
    ) -> discord.Message:
        """Crée le rôle, poste l'annonce avec ses boutons et l'enregistre dans
        `entry["annonces"]` (pour la persistance des boutons et le nettoyage)."""
        channel = await self.bot.fetch_channel(RACES_CHANNEL_ID)
        guild = channel.guild
        role = await guild.create_role(name=role_name[:100], mentionable=True)
        try:
            view = TournoiRegistrationView(role.id, reputation_min)
            msg = await channel.send(embed=embed, view=view)
        except Exception:
            # Pas de rôle orphelin si l'envoi échoue
            await role.delete(reason="Échec de l'annonce du tournoi")
            raise

        entry["annonces"][str(msg.id)] = {
            "channel_id": channel.id,
            "role_id": role.id,
            "reputation_min": reputation_min,
            "expire_at": expire_at,
        }

        notify_role = guild.get_role(RACES_NOTIFY_ROLE_ID)
        if notify_role:
            try:
                await channel.send(notify_role.mention)
            except Exception as e:
                logger.warning("Ping du rôle de notification impossible : %s", e)

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

            if not entry["nouveau_annonce"]:
                if premier_lancement or not TOURNOIS_ANNONCE_CHANNEL_ID:
                    entry["nouveau_annonce"] = True
                else:
                    try:
                        await self._announce_nouveau(champ)
                        entry["nouveau_annonce"] = True
                        changed = True
                    except Exception as e:
                        logger.error("Échec annonce nouveau tournoi %s : %s", cid, e)

            if champ["modeRevelation"] == "IMMEDIAT":
                # Cas particulier : le calendrier complet n'est annoncé que
                # lorsque le tournoi est en EN_COURS (clic "Démarrer"), jamais
                # en PREPARATION — même si le site, lui, montre déjà tout dès
                # la création (règle métier demandée explicitement par le staff).
                if entry["immediat_annonce"] or champ["statut"] != "EN_COURS":
                    continue
                if premier_lancement:
                    entry["immediat_annonce"] = True
                    entry["manches_annoncees"] = [m["id"] for m in champ["manches"]]
                    continue
                try:
                    embed = self._build_calendrier_embed(champ)
                    expire_at = _expiration([m.get("date") for m in champ["manches"]])
                    await self._announce(
                        entry, embed, champ["nom"], champ.get("reputationMin"), expire_at
                    )
                    entry["immediat_annonce"] = True
                    entry["manches_annoncees"] = [m["id"] for m in champ["manches"]]
                    changed = True
                except Exception as e:
                    logger.error("Échec annonce calendrier tournoi %s : %s", cid, e)
                continue

            # DELAI / CLOTURE_PRECEDENTE / MANUEL : une annonce par manche,
            # dès qu'elle passe à revelee=true (peu importe pourquoi — le
            # site a déjà tranché).
            for manche in champ["manches"]:
                if not manche["revelee"]:
                    continue
                if manche["id"] in entry["manches_annoncees"]:
                    continue
                if premier_lancement:
                    entry["manches_annoncees"].append(manche["id"])
                    continue
                try:
                    embed = self._build_manche_embed(champ, manche)
                    role_name = f"{champ['nom']} — Manche {manche['ordre']}"
                    expire_at = _expiration([manche.get("date")])
                    await self._announce(
                        entry, embed, role_name, champ.get("reputationMin"), expire_at
                    )
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


async def setup(bot):
    await bot.add_cog(Tournois(bot))
