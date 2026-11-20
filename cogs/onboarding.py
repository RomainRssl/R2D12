"""Onboarding PADS : règlement, inscription (Pseudo / Prénom / Nom) et vérification.

Parcours d'un nouveau membre
----------------------------
1. Arrivée : le bot lui donne le rôle « Non vérifié » (qui ne voit que #règlement).
2. Dans #règlement, il clique sur « J'accepte le règlement » → Modal
   « Inscription PADS » (Pseudo pré-rempli, Prénom, Nom).
3. À la validation : renommage au format Pseudo[P.Nom], envoi des infos au site
   (POST /api/members/onboarding), puis « Non vérifié » → « Membre ».

Confidentialité
---------------
Le prénom et le nom ne transitent QUE dans l'appel API : jamais stockés dans
data/onboarding.json, jamais écrits dans les logs (console ou salon staff),
jamais affichés hors d'un message éphémère. Toutes les réponses au membre
sont éphémères.

Configuration
-------------
Par serveur dans data/onboarding.json (voir DEFAULT_CONFIG). Secrets dans
l'environnement : ONBOARDING_API_URL, ONBOARDING_API_KEY.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs.onboarding_utils import (
    NAME_MAX,
    PSEUDO_MAX,
    build_nickname,
    default_pseudo,
    normalize,
    utc_now_iso,
    validate_name,
    validate_pseudo,
)

logger = logging.getLogger(__name__)

ONBOARDING_FILE = "data/onboarding.json"
AUTOROLES_FILE = "data/autoroles.json"

DEFAULT_API_URL = "https://paramourduspin.fun/api/members/onboarding"
ONBOARDING_API_URL = (os.getenv("ONBOARDING_API_URL") or DEFAULT_API_URL).strip()
ONBOARDING_API_KEY = os.getenv("ONBOARDING_API_KEY", "").strip()
# Salon staff utilisé si staff_log_channel_id n'est pas défini pour le serveur.
DEFAULT_STAFF_LOG_CHANNEL_ID = int(os.getenv("ONBOARDING_STAFF_LOG_CHANNEL_ID") or "1573330447310786660")

ACCEPT_CUSTOM_ID = "pads:onboarding:accept"
API_TIMEOUT = aiohttp.ClientTimeout(total=10)
RULES_TEXT_MAX = 4000

PRIVACY_NOTICE = (
    "Ces informations sont utilisées uniquement pour la gestion interne de PADS "
    "et ne sont visibles que par le staff."
)
NICKNAME_NOTICE = (
    "Ton pseudo sur le serveur deviendra `Pseudo[Initiale.Nom]` (ex. `Clyde[J.Doe]`). "
    "Ton prénom complet, lui, reste confidentiel."
)
TECHNICAL_ERROR_MSG = (
    "⚠️ Un souci technique empêche la validation, réessaie dans quelques minutes "
    "ou contacte le staff."
)

DEFAULT_CONFIG = {
    "enabled": False,
    "unverified_role_id": None,
    "member_role_id": None,
    "extra_role_ids": [],      # rôles donnés en plus de « Membre » (ex. PILOTE)
    "rules_channel_id": None,
    "rules_message_id": None,
    "staff_log_channel_id": None,
    "rules_version": None,
    "rules_text": "",
}

API_FIELD_LABELS = {
    "discordId": "identifiant Discord",
    "discordUsername": "nom d'utilisateur Discord",
    "pseudo": "Pseudo",
    "serverNickname": "surnom serveur",
    "firstName": "Prénom",
    "lastName": "Nom",
    "guildId": "serveur",
    "rulesVersion": "version du règlement",
    "acceptedRulesAt": "date d'acceptation",
}

NO_MENTIONS = discord.AllowedMentions.none()


# ── Persistance ──────────────────────────────────────────────────────────────


def load_data() -> dict:
    if not os.path.exists(ONBOARDING_FILE):
        return {}
    with open(ONBOARDING_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    """Écriture atomique (fichier temporaire puis remplacement)."""
    os.makedirs("data", exist_ok=True)
    tmp = f"{ONBOARDING_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ONBOARDING_FILE)


def get_config(guild_id: int) -> dict:
    config = dict(DEFAULT_CONFIG)
    config.update(load_data().get(str(guild_id), {}))
    return config


def update_config(guild_id: int, **changes) -> dict:
    data = load_data()
    config = dict(DEFAULT_CONFIG)
    config.update(data.get(str(guild_id), {}))
    config.update(changes)
    data[str(guild_id)] = config
    save_data(data)
    return config


def is_onboarding_active(guild_id: int) -> bool:
    """Utilisé par d'autres cogs (ex. welcome) pour savoir si l'onboarding est actif."""
    try:
        return bool(get_config(guild_id).get("enabled"))
    except (OSError, ValueError):
        return False


def _safe_rules_path(value: str) -> Path | None:
    """Chemin .md relatif au dossier du bot (pas de sortie du dossier)."""
    value = (value or "").strip()
    if "\n" in value or not value.lower().endswith(".md"):
        return None
    base = Path.cwd().resolve()
    path = (base / value).resolve()
    if base not in path.parents:
        return None
    return path


def resolve_rules_text(config: dict) -> str:
    """Texte du règlement : texte brut, ou contenu du fichier .md référencé."""
    raw = config.get("rules_text") or ""
    path = _safe_rules_path(raw)
    if path is not None:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("Fichier de règlement introuvable : %s", raw)
            return ""
    return raw.strip()


def config_missing(config: dict) -> list[str]:
    missing = []
    if not config.get("unverified_role_id"):
        missing.append("rôle « Non vérifié »")
    if not config.get("member_role_id"):
        missing.append("rôle « Membre »")
    if not config.get("rules_channel_id"):
        missing.append("salon du règlement")
    if not config.get("rules_version"):
        missing.append("version du règlement")
    return missing


# ── Vue persistante + Modal ──────────────────────────────────────────────────


class OnboardingView(discord.ui.View):
    """Bouton « J'accepte le règlement » (persistant, custom_id fixe)."""

    def __init__(self, cog: "Onboarding"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="J'accepte le règlement",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id=ACCEPT_CUSTOM_ID,
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.open_modal(interaction)


class OnboardingModal(discord.ui.Modal):
    def __init__(self, cog: "Onboarding", *, pseudo_default: str, is_update: bool):
        super().__init__(
            title="Mise à jour — Inscription PADS" if is_update else "Inscription PADS",
            timeout=600,
        )
        self.cog = cog
        self.pseudo = discord.ui.TextInput(
            label="Pseudo (visible de tous)",
            placeholder="Ton pseudo deviendra Pseudo[Initiale.Nom], ex. Clyde[J.Doe]",
            default=pseudo_default or None,
            min_length=1,
            max_length=PSEUDO_MAX,
            required=True,
        )
        self.first_name = discord.ui.TextInput(
            label="Prénom (confidentiel, staff uniquement)",
            placeholder="Usage interne PADS uniquement, visible seulement par le staff",
            min_length=1,
            max_length=NAME_MAX,
            required=True,
        )
        self.last_name = discord.ui.TextInput(
            label="Nom (apparaîtra dans ton pseudo)",
            placeholder="Usage interne PADS ; seuls l'initiale du prénom et le nom sont affichés",
            min_length=1,
            max_length=NAME_MAX,
            required=True,
        )
        self.add_item(self.pseudo)
        self.add_item(self.first_name)
        self.add_item(self.last_name)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.process_submission(
            interaction,
            pseudo=self.pseudo.value,
            first_name=self.first_name.value,
            last_name=self.last_name.value,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        # Pas de exc_info : la trace pourrait contenir les valeurs saisies.
        logger.error("Erreur inattendue dans le modal d'onboarding : %s", type(error).__name__)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(TECHNICAL_ERROR_MSG, ephemeral=True)
            else:
                await interaction.response.send_message(TECHNICAL_ERROR_MSG, ephemeral=True)
        except discord.HTTPException:
            pass


class RulesTextModal(discord.ui.Modal, title="Texte du règlement"):
    def __init__(self, guild_id: int, current: str):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.text = discord.ui.TextInput(
            label="Règlement (Markdown Discord accepté)",
            style=discord.TextStyle.paragraph,
            default=current[:RULES_TEXT_MAX] or None,
            max_length=RULES_TEXT_MAX,
            required=True,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        update_config(self.guild_id, rules_text=self.text.value.strip())
        await interaction.response.send_message(
            "✅ Texte du règlement enregistré. Utilise `/onboarding publier` pour mettre à jour le message.",
            ephemeral=True,
        )


class MigrateConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Cette confirmation ne t'est pas destinée.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await interaction.response.edit_message(content="⏳ Migration en cours…", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        await interaction.response.edit_message(content="Migration annulée.", embed=None, view=None)
        self.stop()


# ── Cog ──────────────────────────────────────────────────────────────────────


class Onboarding(commands.Cog):
    """Onboarding PADS : règlement, inscription et rôle Membre."""

    onboarding_group = app_commands.Group(
        name="onboarding",
        description="Onboarding PADS : règlement, inscription et vérification des membres",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self._in_progress: set[tuple[int, int]] = set()

    async def cog_load(self):
        self.session = aiohttp.ClientSession(headers={"User-Agent": "R2D12-Bot"})
        self.bot.add_view(OnboardingView(self))
        if not ONBOARDING_API_KEY:
            logger.warning("ONBOARDING_API_KEY absent : les inscriptions échoueront (401).")

    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # Les commandes admin : défaut Discord (administrateur) + vérification à l'exécution.
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if interaction.guild is None or perms is None or not perms.administrator:
            raise app_commands.MissingPermissions(["administrator"])
        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, (app_commands.MissingPermissions, app_commands.NoPrivateMessage)):
            msg = "⛔ Cette commande est réservée aux administrateurs du serveur."
        else:
            logger.error("Erreur dans une commande /onboarding : %r", error)
            msg = "❌ Une erreur est survenue pendant l'exécution de la commande."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    # ── Helpers ──────────────────────────────────────────────────────────────

    def staff_channel(self, guild: discord.Guild, config: dict) -> discord.abc.Messageable | None:
        channel_id = config.get("staff_log_channel_id") or DEFAULT_STAFF_LOG_CHANNEL_ID
        return guild.get_channel(int(channel_id)) if channel_id else None

    async def staff_log(self, guild: discord.Guild, config: dict, message: str):
        """Log staff. NE JAMAIS y mettre de prénom / nom."""
        channel = self.staff_channel(guild, config)
        if channel is None:
            logger.warning("[onboarding] salon staff introuvable (guild %s)", guild.id)
            return
        try:
            await channel.send(message, allowed_mentions=NO_MENTIONS)
        except discord.HTTPException as exc:
            logger.warning("[onboarding] envoi au salon staff impossible : %s", exc)

    def build_rules_embed(self, guild: discord.Guild, config: dict) -> discord.Embed:
        embed = discord.Embed(
            title=f"📜 Règlement — {guild.name}",
            description=resolve_rules_text(config)[:4096] or "_Règlement non défini._",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="✅ Pour accéder au serveur",
            value=(
                "Lis le règlement puis clique sur **J'accepte le règlement**. "
                "Un formulaire te demandera ton pseudo, ton prénom et ton nom.\n"
                f"{NICKNAME_NOTICE}"
            ),
            inline=False,
        )
        embed.add_field(name="🔒 Confidentialité", value=PRIVACY_NOTICE, inline=False)
        embed.set_footer(text=f"Version du règlement : {config.get('rules_version') or '—'}")
        return embed

    async def post_onboarding(self, payload: dict) -> tuple[int | None, dict | None, str]:
        """POST vers le site. Retourne (status, body, erreur réseau éventuelle).

        1 nouvel essai automatique sur erreur réseau / timeout / 5xx.
        Le payload n'est jamais journalisé.
        """
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"User-Agent": "R2D12-Bot"})
        headers = {"Authorization": f"Bearer {ONBOARDING_API_KEY}", "Content-Type": "application/json"}
        status, body, error = None, None, ""
        for attempt in (1, 2):
            try:
                async with self.session.post(
                    ONBOARDING_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=API_TIMEOUT,
                    allow_redirects=False,
                ) as resp:
                    status = resp.status
                    try:
                        body = await resp.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError):
                        body = None
                    if status >= 500 and attempt == 1:
                        logger.warning("[onboarding] API %s, nouvel essai", status)
                        await asyncio.sleep(1)
                        continue
                    return status, body if isinstance(body, dict) else None, ""
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                status, body = None, None
                error = "timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
                logger.warning("[onboarding] API injoignable (%s), essai %s/2", error, attempt)
                if attempt == 1:
                    await asyncio.sleep(1)
        return status, None, error

    # ── Bouton ───────────────────────────────────────────────────────────────

    async def open_modal(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Ce bouton ne fonctionne que sur le serveur.", ephemeral=True)
            return
        config = get_config(guild.id)
        if not config.get("enabled") or config_missing(config):
            await interaction.response.send_message(
                "L'inscription est momentanément indisponible. Contacte le staff.", ephemeral=True
            )
            return
        if (guild.id, member.id) in self._in_progress:
            await interaction.response.send_message(
                "⏳ Ta validation est déjà en cours, patiente quelques secondes.", ephemeral=True
            )
            return
        member_role = guild.get_role(int(config["member_role_id"]))
        is_update = member_role is not None and member_role in member.roles
        await interaction.response.send_modal(
            OnboardingModal(self, pseudo_default=default_pseudo(member.display_name), is_update=is_update)
        )

    # ── Soumission ───────────────────────────────────────────────────────────

    async def process_submission(self, interaction: discord.Interaction, *, pseudo: str, first_name: str, last_name: str):
        guild = interaction.guild
        member = interaction.user
        key = (guild.id, member.id)
        if key in self._in_progress:
            await interaction.followup.send("⏳ Ta validation est déjà en cours.", ephemeral=True)
            return
        self._in_progress.add(key)
        try:
            await self._process(interaction, guild, member, pseudo, first_name, last_name)
        finally:
            self._in_progress.discard(key)

    async def _process(self, interaction, guild: discord.Guild, member: discord.Member, pseudo, first_name, last_name):
        config = get_config(guild.id)
        if not config.get("enabled") or config_missing(config):
            await interaction.followup.send("L'inscription est momentanément indisponible. Contacte le staff.", ephemeral=True)
            return
        unverified_role = guild.get_role(int(config["unverified_role_id"]))
        member_role = guild.get_role(int(config["member_role_id"]))
        if member_role is None:
            await interaction.followup.send(TECHNICAL_ERROR_MSG, ephemeral=True)
            await self.staff_log(guild, config, f"⚠️ Onboarding : rôle « Membre » introuvable (validation de {member.mention} bloquée).")
            return

        # 1. Validation locale
        pseudo = normalize(pseudo)
        first_name = normalize(first_name)
        last_name = normalize(last_name)
        errors = [
            e for e in (
                validate_pseudo(pseudo),
                validate_name(first_name, "prénom"),
                validate_name(last_name, "nom"),
            ) if e
        ]
        if errors:
            await interaction.followup.send(
                "❌ Certaines informations ne sont pas valides :\n" + "\n".join(f"• {e}" for e in errors)
                + "\n\nClique à nouveau sur le bouton pour corriger.",
                ephemeral=True,
            )
            return

        was_member = member_role in member.roles

        # 2. Renommage AVANT l'appel API
        old_nick = member.nick
        new_nick = build_nickname(pseudo, first_name, last_name)
        applied_nick, renamed, rename_error = await self._rename(guild, member, new_nick)
        if rename_error:
            await self.staff_log(guild, config, f"⚠️ Renommage impossible pour {member.mention} : {rename_error}.")

        # 3. Appel API
        payload = {
            "discordId": str(member.id),
            "discordUsername": member.name,
            "pseudo": pseudo,
            "serverNickname": applied_nick,
            "firstName": first_name,
            "lastName": last_name,
            "guildId": str(guild.id),
            "rulesVersion": str(config["rules_version"]),
            "acceptedRulesAt": utc_now_iso(),
        }
        status, body, net_error = await self.post_onboarding(payload)
        del payload, first_name, last_name

        # 4. Succès
        if status in (200, 201):
            role_error = await self._grant_member(member, member_role, unverified_role, self._extra_roles(guild, config))
            if role_error:
                await self.staff_log(guild, config, f"⚠️ Rôles non mis à jour pour {member.mention} : {role_error}.")
            version = config["rules_version"]
            if was_member:
                await self.staff_log(guild, config, f"🔁 {member.mention} a mis à jour ses informations (règlement v{version}).")
                text = "✅ Tes informations ont bien été mises à jour."
            else:
                await self.staff_log(guild, config, f"✅ {member.mention} a validé le règlement (v{version}).")
                text = f"✅ Bienvenue sur **{guild.name}** ! Tu as maintenant accès au serveur."
                if not role_error:
                    self.bot.dispatch("pads_member_verified", member)
            if applied_nick:
                text += f"\nTon pseudo sur le serveur : **{discord.utils.escape_markdown(applied_nick)}**"
            else:
                text += "\nTon pseudo n'a pas pu être modifié automatiquement, le staff a été prévenu."
            if role_error:
                text += "\n⚠️ Tes rôles n'ont pas pu être mis à jour, le staff a été prévenu."
            await interaction.followup.send(text, ephemeral=True)
            return

        # 5/6. Échec : on remet l'ancien surnom, on ne touche pas aux rôles
        if renamed:
            await self._restore_nick(member, old_nick)

        if status == 400:
            fields = self._error_fields(body)
            detail = f" ({', '.join(fields)})" if fields else ""
            await interaction.followup.send(
                f"❌ Le site a refusé certaines informations{detail}. Vérifie ta saisie "
                "(lettres, espaces, tirets et apostrophes uniquement pour le prénom et le nom) "
                "puis clique à nouveau sur le bouton.",
                ephemeral=True,
            )
            await self.staff_log(guild, config, f"ℹ️ Inscription de {member.mention} refusée par le site (400, saisie invalide).")
            return

        code = str(status) if status is not None else (net_error or "erreur réseau")
        await interaction.followup.send(TECHNICAL_ERROR_MSG, ephemeral=True)
        await self.staff_log(
            guild, config,
            f"❌ Échec de l'envoi au site pour {member.mention} (code : `{code}`). Rôles inchangés.",
        )

    @staticmethod
    def _extra_roles(guild: discord.Guild, config: dict) -> list[discord.Role]:
        roles = (guild.get_role(int(rid)) for rid in config.get("extra_role_ids") or [])
        return [r for r in roles if r is not None]

    @staticmethod
    def _error_fields(body: dict | None) -> list[str]:
        fields = []
        for detail in (body or {}).get("details") or []:
            path = detail.get("path") if isinstance(detail, dict) else None
            if isinstance(path, list):
                path = path[0] if path else None
            label = API_FIELD_LABELS.get(str(path)) if path is not None else None
            if label and label not in fields:
                fields.append(label)
        return fields

    async def _rename(self, guild: discord.Guild, member: discord.Member, new_nick: str) -> tuple[str | None, bool, str]:
        """Retourne (surnom appliqué ou None, renommé ?, raison technique d'échec)."""
        if member.nick == new_nick:
            return new_nick, False, ""
        me = guild.me
        if member.id == guild.owner_id:
            return None, False, "propriétaire du serveur (Discord interdit de le renommer)"
        if not me.guild_permissions.manage_nicknames:
            return None, False, "permission « Gérer les pseudos » manquante"
        if member.top_role >= me.top_role:
            return None, False, "rôle du membre au-dessus (ou au niveau) du rôle du bot"
        try:
            await member.edit(nick=new_nick, reason="Onboarding PADS")
        except discord.Forbidden:
            return None, False, "refusé par Discord (permissions)"
        except discord.HTTPException as exc:
            return None, False, f"erreur Discord {exc.status}"
        return new_nick, True, ""

    async def _restore_nick(self, member: discord.Member, old_nick: str | None):
        try:
            await member.edit(nick=old_nick, reason="Onboarding PADS : annulation")
        except discord.HTTPException as exc:
            logger.warning("[onboarding] restauration du surnom impossible (%s) pour %s", exc.status, member.id)

    async def _grant_member(self, member: discord.Member, member_role: discord.Role,
                            unverified_role: discord.Role | None, extra_roles: list[discord.Role]) -> str:
        try:
            to_add = [r for r in [member_role, *extra_roles] if r not in member.roles]
            if to_add:
                await member.add_roles(*to_add, reason="Onboarding PADS : règlement accepté")
            if unverified_role is not None and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="Onboarding PADS : règlement accepté")
        except discord.Forbidden:
            return "permission « Gérer les rôles » manquante ou rôle du bot trop bas"
        except discord.HTTPException as exc:
            return f"erreur Discord {exc.status}"
        return ""

    # ── Arrivée d'un membre ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        config = get_config(member.guild.id)
        if not config.get("enabled") or not config.get("unverified_role_id"):
            return
        role = member.guild.get_role(int(config["unverified_role_id"]))
        if role is None:
            await self.staff_log(member.guild, config, f"⚠️ Rôle « Non vérifié » introuvable : impossible de l'attribuer à {member.mention}.")
            return
        try:
            await member.add_roles(role, reason="Onboarding PADS : nouveau membre")
        except discord.HTTPException as exc:
            await self.staff_log(
                member.guild, config,
                f"⚠️ Impossible de donner « Non vérifié » à {member.mention} (erreur {getattr(exc, 'status', '?')}).",
            )

    # ── Commandes admin ──────────────────────────────────────────────────────

    @onboarding_group.command(name="setup", description="Définir les rôles, le salon du règlement et la version")
    @app_commands.describe(
        role_non_verifie="Rôle donné à l'arrivée (ne voit que le règlement)",
        role_membre="Rôle donné après validation du règlement",
        salon_reglement="Salon où sera publié le règlement",
        version_reglement="Version du règlement, ex. 2026-11",
        salon_logs="Salon staff pour les retours (par défaut : salon staff PADS)",
        role_supplementaire="Rôle donné en plus de « Membre » à la validation (ex. PILOTE)",
    )
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        role_non_verifie: discord.Role,
        role_membre: discord.Role,
        salon_reglement: discord.TextChannel,
        version_reglement: app_commands.Range[str, 1, 32],
        salon_logs: discord.TextChannel | None = None,
        role_supplementaire: discord.Role | None = None,
    ):
        guild = interaction.guild
        problems = []
        if role_non_verifie == role_membre:
            problems.append("Les deux rôles doivent être différents.")
        if role_supplementaire is not None and role_supplementaire in (role_non_verifie, role_membre):
            problems.append("Le rôle supplémentaire doit être différent de « Non vérifié » et « Membre ».")
        for role in (role_non_verifie, role_membre, *([role_supplementaire] if role_supplementaire else [])):
            if role.is_default() or role.managed:
                problems.append(f"{role.mention} ne peut pas être utilisé (rôle @everyone ou géré par une intégration).")
        if problems:
            await interaction.response.send_message("❌ " + "\n".join(problems), ephemeral=True)
            return

        config = update_config(
            guild.id,
            unverified_role_id=role_non_verifie.id,
            member_role_id=role_membre.id,
            rules_channel_id=salon_reglement.id,
            rules_version=version_reglement.strip(),
            staff_log_channel_id=salon_logs.id if salon_logs else None,
            extra_role_ids=[role_supplementaire.id] if role_supplementaire else [],
        )
        embed = discord.Embed(title="Onboarding configuré", color=discord.Color.green())
        embed.add_field(name="Non vérifié", value=role_non_verifie.mention)
        embed.add_field(name="Membre", value=role_membre.mention)
        embed.add_field(name="Rôle supplémentaire", value=role_supplementaire.mention if role_supplementaire else "—")
        embed.add_field(name="Salon règlement", value=salon_reglement.mention)
        embed.add_field(name="Version", value=config["rules_version"])
        staff = self.staff_channel(guild, config)
        embed.add_field(name="Salon staff", value=staff.mention if staff else "`introuvable`")
        embed.add_field(name="Activé", value="Oui" if config["enabled"] else "Non")
        embed.set_footer(text="Étapes suivantes : /onboarding reglement → publier → statut → activer")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @onboarding_group.command(name="reglement", description="Modifier le texte du règlement (ou pointer vers un fichier .md)")
    @app_commands.describe(fichier="Optionnel : chemin d'un fichier .md relatif au dossier du bot")
    async def rules_cmd(self, interaction: discord.Interaction, fichier: str | None = None):
        guild_id = interaction.guild_id
        if fichier:
            path = _safe_rules_path(fichier)
            if path is None or not path.is_file():
                await interaction.response.send_message(
                    "❌ Fichier introuvable. Indique un chemin `.md` relatif au dossier du bot (ex. `data/reglement.md`).",
                    ephemeral=True,
                )
                return
            content = path.read_text(encoding="utf-8").strip()
            if not content or len(content) > 4096:
                await interaction.response.send_message("❌ Le fichier doit contenir entre 1 et 4096 caractères.", ephemeral=True)
                return
            update_config(guild_id, rules_text=fichier.strip())
            await interaction.response.send_message(
                f"✅ Le règlement sera lu depuis `{fichier.strip()}` ({len(content)} caractères). "
                "Utilise `/onboarding publier` pour mettre à jour le message.",
                ephemeral=True,
            )
            return
        config = get_config(guild_id)
        current = "" if _safe_rules_path(config.get("rules_text") or "") else (config.get("rules_text") or "")
        await interaction.response.send_modal(RulesTextModal(guild_id, current))

    @onboarding_group.command(name="publier", description="Publier (ou mettre à jour) le message du règlement avec le bouton")
    async def publish_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        config = get_config(guild.id)
        missing = config_missing(config)
        if missing:
            await interaction.response.send_message(f"❌ Configuration incomplète : {', '.join(missing)}. Lance `/onboarding setup`.", ephemeral=True)
            return
        if not resolve_rules_text(config):
            await interaction.response.send_message("❌ Aucun texte de règlement. Lance `/onboarding reglement`.", ephemeral=True)
            return
        channel = guild.get_channel(int(config["rules_channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Salon du règlement introuvable.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        embed = self.build_rules_embed(guild, config)
        view = OnboardingView(self)
        try:
            message = None
            if config.get("rules_message_id"):
                try:
                    message = await channel.fetch_message(int(config["rules_message_id"]))
                except discord.NotFound:
                    message = None
            if message is not None:
                await message.edit(embed=embed, view=view)
                action = "mis à jour"
            else:
                message = await channel.send(embed=embed, view=view)
                update_config(guild.id, rules_message_id=message.id)
                action = "publié"
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ Je n'ai pas les permissions nécessaires dans {channel.mention} "
                "(voir le salon, envoyer des messages, intégrer des liens, lire l'historique).",
                ephemeral=True,
            )
            return
        await interaction.followup.send(f"✅ Règlement {action} : {message.jump_url}", ephemeral=True)

    @onboarding_group.command(name="statut", description="Voir la configuration et vérifier les permissions du bot")
    async def status_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        config = get_config(guild.id)
        me = guild.me
        checks: list[str] = []

        def check(ok: bool, text: str, warn: bool = False):
            checks.append(f"{'✅' if ok else ('⚠️' if warn else '❌')} {text}")

        unverified = guild.get_role(int(config["unverified_role_id"])) if config.get("unverified_role_id") else None
        member_role = guild.get_role(int(config["member_role_id"])) if config.get("member_role_id") else None
        rules_channel = guild.get_channel(int(config["rules_channel_id"])) if config.get("rules_channel_id") else None
        staff = self.staff_channel(guild, config)

        check(bool(ONBOARDING_API_KEY), "Clé API (`ONBOARDING_API_KEY`) définie dans l'environnement")
        check(self.bot.intents.members, "Intent « members » actif")
        check(unverified is not None, "Rôle « Non vérifié » configuré et existant")
        check(member_role is not None, "Rôle « Membre » configuré et existant")
        check(me.guild_permissions.manage_roles, "Permission « Gérer les rôles »")
        check(me.guild_permissions.manage_nicknames, "Permission « Gérer les pseudos »")
        extra_roles = self._extra_roles(guild, config)
        if len(extra_roles) != len(config.get("extra_role_ids") or []):
            check(False, "Un rôle supplémentaire configuré est introuvable")
        for role, name in ((unverified, "Non vérifié"), (member_role, "Membre"), *((r, r.name) for r in extra_roles)):
            if role is not None:
                check(me.top_role > role, f"Rôle du bot au-dessus de « {name} »")
        if isinstance(rules_channel, discord.TextChannel):
            p = rules_channel.permissions_for(me)
            check(p.view_channel and p.send_messages and p.embed_links and p.read_message_history,
                  f"Accès du bot à {rules_channel.mention} (voir, écrire, intégrer, historique)")
            if unverified is not None:
                pu = rules_channel.permissions_for(unverified)
                check(pu.view_channel, f"« Non vérifié » voit {rules_channel.mention}")
                check(not pu.send_messages, f"« Non vérifié » ne peut pas écrire dans {rules_channel.mention}", warn=True)
        else:
            check(False, "Salon du règlement configuré et existant")
        check(bool(resolve_rules_text(config)), "Texte du règlement défini")
        check(bool(config.get("rules_message_id")), "Message du règlement publié", warn=True)
        if staff is not None:
            ps = staff.permissions_for(me)
            check(ps.view_channel and ps.send_messages, f"Salon staff {staff.mention} accessible")
        else:
            check(False, "Salon staff introuvable", warn=True)
        if member_role is not None:
            try:
                with open(AUTOROLES_FILE, encoding="utf-8") as f:
                    autoroles = json.load(f).get(str(guild.id), [])
            except (OSError, ValueError):
                autoroles = []
            check(member_role.id not in autoroles,
                  "« Membre » n'est PAS dans les auto-rôles (sinon la vérification est contournée)")

        embed = discord.Embed(
            title="Onboarding — statut",
            color=discord.Color.green() if config.get("enabled") else discord.Color.orange(),
        )
        embed.add_field(name="Activé", value="Oui" if config.get("enabled") else "Non")
        embed.add_field(name="Version", value=config.get("rules_version") or "—")
        embed.add_field(name="API", value=f"`{ONBOARDING_API_URL}`", inline=False)
        embed.add_field(name="Non vérifié", value=unverified.mention if unverified else "—")
        embed.add_field(name="Membre", value=member_role.mention if member_role else "—")
        embed.add_field(name="Rôles en plus", value=" ".join(r.mention for r in extra_roles) or "—")
        embed.add_field(name="Salon règlement", value=rules_channel.mention if rules_channel else "—")
        embed.add_field(name="Salon staff", value=staff.mention if staff else "—")
        embed.add_field(name="Vérifications", value="\n".join(checks)[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @onboarding_group.command(name="activer", description="Activer l'onboarding (rôle « Non vérifié » à l'arrivée)")
    async def enable_cmd(self, interaction: discord.Interaction):
        config = get_config(interaction.guild_id)
        missing = config_missing(config)
        if missing:
            await interaction.response.send_message(f"❌ Configuration incomplète : {', '.join(missing)}.", ephemeral=True)
            return
        update_config(interaction.guild_id, enabled=True)
        warn = "" if config.get("rules_message_id") else "\n⚠️ Le règlement n'est pas encore publié (`/onboarding publier`)."
        if not ONBOARDING_API_KEY:
            warn += "\n⚠️ `ONBOARDING_API_KEY` absent : les inscriptions échoueront."
        await interaction.response.send_message(
            "✅ Onboarding activé. Les nouveaux membres recevront « Non vérifié »." + warn, ephemeral=True
        )

    @onboarding_group.command(name="desactiver", description="Désactiver l'onboarding")
    async def disable_cmd(self, interaction: discord.Interaction):
        update_config(interaction.guild_id, enabled=False)
        await interaction.response.send_message(
            "Onboarding désactivé : plus de rôle « Non vérifié » à l'arrivée et le bouton est suspendu.",
            ephemeral=True,
        )

    @onboarding_group.command(name="migrer-existants", description="Donner « Membre » à tous les membres humains actuels (sauf « Non vérifié »)")
    async def migrate_cmd(self, interaction: discord.Interaction):
        guild = interaction.guild
        config = get_config(guild.id)
        member_role = guild.get_role(int(config["member_role_id"])) if config.get("member_role_id") else None
        unverified = guild.get_role(int(config["unverified_role_id"])) if config.get("unverified_role_id") else None
        if member_role is None:
            await interaction.response.send_message("❌ Rôle « Membre » non configuré. Lance `/onboarding setup`.", ephemeral=True)
            return
        if not guild.me.guild_permissions.manage_roles or guild.me.top_role <= member_role:
            await interaction.response.send_message(
                "❌ Je ne peux pas attribuer ce rôle : permission « Gérer les rôles » manquante ou rôle du bot trop bas.",
                ephemeral=True,
            )
            return

        if not guild.chunked:
            await guild.chunk()
        targets = [
            m for m in guild.members
            if not m.bot and member_role not in m.roles and (unverified is None or unverified not in m.roles)
        ]
        if not targets:
            await interaction.response.send_message("Aucun membre à migrer : tout le monde a déjà le rôle.", ephemeral=True)
            return

        view = MigrateConfirmView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ Je vais donner {member_role.mention} à **{len(targets)}** membre(s) humain(s) "
            f"qui ne l'ont pas encore (membres avec « Non vérifié » exclus). Confirmer ?",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            if view.confirmed is None:
                await interaction.edit_original_response(content="Délai dépassé, migration annulée.", view=None)
            return

        ok, failed = 0, 0
        for m in targets:
            try:
                await m.add_roles(member_role, reason=f"Onboarding PADS : migration par {interaction.user}")
                ok += 1
            except discord.HTTPException:
                failed += 1
        report = f"✅ Migration terminée : {ok} membre(s) ont reçu {member_role.mention}"
        report += f", {failed} échec(s)." if failed else "."
        await interaction.edit_original_response(content=report, view=None)
        await self.staff_log(guild, config, f"📦 Migration onboarding par {interaction.user.mention} : {ok} rôle(s) « Membre » ajouté(s), {failed} échec(s).")


async def setup(bot: commands.Bot):
    await bot.add_cog(Onboarding(bot))
