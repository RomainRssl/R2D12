"""Attribution de rôle en masse.

/role_masse source:<Role> cible:<Role> simulation:<bool=True>
  - simulation=True (défaut) : aperçu sans modification.
  - simulation=False : attribution réelle avec progression et récapitulatif.

Verrou par guilde : une seule exécution à la fois.
Repli si l'interaction expire (> 15 min) : envoi du résumé dans le salon
staff de l'onboarding (data/onboarding.json ou ONBOARDING_STAFF_LOG_CHANNEL_ID).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

ONBOARDING_FILE = "data/onboarding.json"
DEFAULT_STAFF_LOG_CHANNEL_ID = int(os.getenv("ONBOARDING_STAFF_LOG_CHANNEL_ID") or "0")

PROGRESS_EVERY = 50


def _staff_channel(guild: discord.Guild) -> discord.abc.Messageable | None:
    """Retourne le salon staff onboarding si configuré, sinon celui de l'env var."""
    try:
        with open(ONBOARDING_FILE, encoding="utf-8") as f:
            data = json.load(f)
        channel_id = data.get(str(guild.id), {}).get("staff_log_channel_id")
    except (OSError, ValueError):
        channel_id = None
    if not channel_id and DEFAULT_STAFF_LOG_CHANNEL_ID:
        channel_id = DEFAULT_STAFF_LOG_CHANNEL_ID
    return guild.get_channel(int(channel_id)) if channel_id else None


class RoleMasse(commands.Cog):
    """Attribution de rôle en masse par rôle source."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._running: set[int] = set()

    @app_commands.command(
        name="role_masse",
        description="Donne un rôle cible à tous les membres ayant un rôle source",
    )
    @app_commands.describe(
        source="Rôle que les membres doivent avoir",
        cible="Rôle à attribuer",
        simulation="Aperçu sans modification (défaut : Oui)",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_masse(
        self,
        interaction: discord.Interaction,
        source: discord.Role,
        cible: discord.Role,
        simulation: bool = True,
    ):
        guild = interaction.guild
        me = guild.me

        # ── Vérifications préalables ─────────────────────────────────────────

        if not me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "❌ Je n'ai pas la permission « Gérer les rôles ».", ephemeral=True
            )
            return

        if cible.is_default():
            await interaction.response.send_message(
                "❌ Le rôle cible ne peut pas être @everyone.", ephemeral=True
            )
            return

        if cible.managed:
            await interaction.response.send_message(
                "❌ Le rôle cible est géré par une intégration (booster, bot…) et ne peut pas être attribué manuellement.",
                ephemeral=True,
            )
            return

        if cible >= me.top_role:
            await interaction.response.send_message(
                f"❌ Le rôle {cible.mention} est au-dessus (ou au niveau) du rôle le plus haut du bot. "
                "Monte le rôle du bot dans la hiérarchie.",
                ephemeral=True,
            )
            return

        user_top = interaction.user.top_role
        if cible >= user_top:
            await interaction.response.send_message(
                f"❌ Tu ne peux pas attribuer {cible.mention} car ce rôle est au-dessus (ou au niveau) de ton rôle le plus haut.",
                ephemeral=True,
            )
            return

        if guild.id in self._running:
            await interaction.response.send_message(
                "⏳ Une attribution en masse est déjà en cours sur ce serveur. Réessaie dans quelques instants.",
                ephemeral=True,
            )
            return

        # ── Chargement des membres ───────────────────────────────────────────

        await interaction.response.defer(ephemeral=True, thinking=True)

        if not guild.chunked:
            await guild.chunk()

        targets = [
            m for m in guild.members
            if not m.bot and source in m.roles and cible not in m.roles
        ]
        total_source = sum(1 for m in guild.members if not m.bot and source in m.roles)
        already = total_source - len(targets)

        # ── Mode simulation ──────────────────────────────────────────────────

        if simulation:
            embed = discord.Embed(
                title="🔍 Simulation — attribution en masse",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Rôle source", value=source.mention, inline=True)
            embed.add_field(name="Rôle cible", value=cible.mention, inline=True)
            embed.add_field(name="​", value="​", inline=True)
            embed.add_field(name="Membres avec le rôle source", value=str(total_source), inline=True)
            embed.add_field(name="Ont déjà la cible", value=str(already), inline=True)
            embed.add_field(name="À traiter", value=str(len(targets)), inline=True)
            if not targets:
                embed.description = "✅ Tous les membres concernés ont déjà le rôle cible. Aucune action nécessaire."
            else:
                embed.description = (
                    f"**{len(targets)}** membre(s) recevraient {cible.mention}.\n"
                    "Relance avec `simulation:Non` pour l'exécuter."
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ── Mode réel ────────────────────────────────────────────────────────

        if not targets:
            await interaction.followup.send(
                f"✅ Tous les membres ayant {source.mention} ont déjà {cible.mention}. Aucune action nécessaire.",
                ephemeral=True,
            )
            return

        self._running.add(guild.id)
        ok = 0
        failed: list[discord.Member] = []

        try:
            reason = f"Ajout en masse par {interaction.user} ({interaction.user.id})"
            for i, member in enumerate(targets, 1):
                try:
                    await member.add_roles(cible, reason=reason)
                    ok += 1
                except discord.HTTPException as exc:
                    logger.warning("[role_masse] échec pour %s (%s) : %s", member, member.id, exc)
                    failed.append(member)

                if i % PROGRESS_EVERY == 0:
                    try:
                        await interaction.edit_original_response(
                            content=f"⏳ Progression : {i}/{len(targets)} membres traités ({ok} succès, {len(failed)} échecs)…"
                        )
                    except discord.HTTPException:
                        pass

        finally:
            self._running.discard(guild.id)

        # ── Récapitulatif ────────────────────────────────────────────────────

        embed = discord.Embed(
            title="✅ Attribution en masse terminée",
            color=discord.Color.green() if not failed else discord.Color.orange(),
        )
        embed.add_field(name="Rôle source", value=source.mention, inline=True)
        embed.add_field(name="Rôle cible", value=cible.mention, inline=True)
        embed.add_field(name="​", value="​", inline=True)
        embed.add_field(name="Traités", value=str(len(targets)), inline=True)
        embed.add_field(name="Succès", value=str(ok), inline=True)
        embed.add_field(name="Échecs", value=str(len(failed)), inline=True)
        if failed:
            names = ", ".join(m.mention for m in failed[:20])
            if len(failed) > 20:
                names += f" … (+{len(failed) - 20})"
            embed.add_field(name="Membres en échec", value=names, inline=False)
        embed.set_footer(text=f"Lancé par {interaction.user}")

        try:
            await interaction.edit_original_response(content=None, embed=embed)
        except discord.HTTPException:
            # Jeton expiré : repli vers le salon staff
            staff = _staff_channel(guild)
            if staff:
                try:
                    await staff.send(
                        f"📋 **Résultat `/role_masse`** (lancé par {interaction.user.mention})",
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException as exc:
                    logger.error("[role_masse] impossible d'envoyer le résumé dans le salon staff : %s", exc)
            else:
                logger.warning("[role_masse] jeton expiré et salon staff introuvable — résumé perdu.")

        logger.info(
            "[role_masse] guild=%s source=%s cible=%s traités=%s ok=%s échecs=%s par %s",
            guild.id, source.id, cible.id, len(targets), ok, len(failed), interaction.user.id,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleMasse(bot))
