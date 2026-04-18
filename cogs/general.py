import discord
from discord import app_commands
from discord.ext import commands
import time


class General(commands.Cog):
    """Commandes générales du bot R2D12."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Affiche la latence du bot")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="Pong !",
            description=f"Latence : **{latency}ms**",
            color=discord.Color.green() if latency < 100 else discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Liste toutes les commandes disponibles")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="R2D12 — Aide",
            description="Voici toutes les commandes disponibles :",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Général",
            value=(
                "`/ping` — Latence du bot\n"
                "`/help` — Cette aide\n"
                "`/serverinfo` — Infos sur le serveur\n"
                "`/userinfo [@membre]` — Infos sur un membre"
            ),
            inline=False,
        )
        embed.add_field(
            name="Modération",
            value=(
                "`/kick @membre [raison]` — Expulser un membre\n"
                "`/ban @membre [raison]` — Bannir un membre\n"
                "`/clear [nombre]` — Supprimer des messages"
            ),
            inline=False,
        )
        embed.add_field(
            name="Templates & Annonces",
            value=(
                "`/template creer <nom> <message>` — Créer un template avec `{variables}`\n"
                "`/template utiliser <nom> [#salon]` — Utiliser un template (formulaire)\n"
                "`/template liste` — Voir tous les templates\n"
                "`/template supprimer <nom>` — Supprimer un template\n"
                "`/annonce #salon <titre> <message>` — Envoyer une annonce formatée"
            ),
            inline=False,
        )
        embed.add_field(
            name="Bienvenue",
            value=(
                "`/bienvenue configurer #salon [message]` — Configurer le message d'accueil\n"
                "`/bienvenue tester` — Prévisualiser le message de bienvenue\n"
                "`/bienvenue statut` — Voir la configuration actuelle\n"
                "`/bienvenue desactiver` — Désactiver les messages de bienvenue"
            ),
            inline=False,
        )
        embed.add_field(
            name="Anniversaires",
            value=(
                "`/anniversaire enregistrer <jour> <mois>` — Enregistrer votre anniversaire\n"
                "`/anniversaire supprimer` — Supprimer votre anniversaire\n"
                "`/anniversaire prochains` — Voir les prochains anniversaires\n"
                "`/anniversaire configurer #salon [message]` — Configurer le salon (admin)\n"
                "`/anniversaire tester` — Prévisualiser le message (admin)\n"
                "`/anniversaire statut` — Voir la configuration (admin)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Modération avancée",
            value=(
                "`/warn @membre [raison]` — Avertir un membre\n"
                "`/warnings @membre` — Voir les avertissements\n"
                "`/clearwarnings @membre` — Effacer les avertissements\n"
                "`/mute @membre [minutes] [raison]` — Mettre en sourdine\n"
                "`/unmute @membre` — Retirer la sourdine\n"
                "`/unban <user_id>` — Débannir"
            ),
            inline=False,
        )
        embed.add_field(
            name="Logs",
            value=(
                "`/logs configurer #salon` — Définir le salon de logs\n"
                "`/logs desactiver` — Désactiver les logs\n"
                "`/logs statut` — Voir la configuration"
            ),
            inline=False,
        )
        embed.add_field(
            name="Gestion des rôles",
            value=(
                "`/role creer <nom> [couleur] [mentionnable] [affiché séparément]` — Créer un rôle\n"
                "`/role supprimer @role` — Supprimer un rôle\n"
                "`/role modifier @role [nom] [couleur]` — Modifier un rôle\n"
                "`/role liste` — Voir tous les rôles\n"
                "`/role permissions-voir @role` — Voir les permissions d'un rôle\n"
                "`/role permissions-ajouter @role <permission>` — Accorder une permission\n"
                "`/role permissions-retirer @role <permission>` — Retirer une permission"
            ),
            inline=False,
        )
        embed.add_field(
            name="Rôles automatiques",
            value=(
                "`/autorole ajouter @role` — Ajouter un rôle automatique\n"
                "`/autorole retirer @role` — Retirer un rôle automatique\n"
                "`/autorole liste` — Voir les rôles configurés"
            ),
            inline=False,
        )
        embed.add_field(
            name="Remplacement de mots",
            value=(
                "`/remplacer ajouter <mot> <remplacement>` — Ajouter une règle\n"
                "`/remplacer retirer <mot>` — Supprimer une règle\n"
                "`/remplacer liste` — Voir toutes les règles\n"
                "`/remplacer tester <phrase>` — Tester une phrase\n"
                "`/remplacer activer / desactiver` — Activer ou désactiver"
            ),
            inline=False,
        )
        embed.add_field(
            name="Rôles réactions (boutons)",
            value=(
                "`/rolerole creer #salon <titre> <desc>` — Créer un panneau\n"
                "`/rolerole ajouter <msg_id> @role <label>` — Ajouter un bouton\n"
                "`/rolerole supprimer <msg_id>` — Supprimer un panneau"
            ),
            inline=False,
        )
        embed.add_field(
            name="Rôles réactions (emoji)",
            value=(
                "`/emojirole ajouter <msg_id> <emoji> @role` — Associer un emoji à un rôle sur un message\n"
                "`/emojirole retirer <msg_id> <emoji>` — Supprimer l'association\n"
                "`/emojirole liste` — Voir toutes les associations"
            ),
            inline=False,
        )
        embed.add_field(
            name="Sondages",
            value=(
                "`/sondage <question> <opt1> <opt2> [opt3-5] [durée_h]` — Créer un sondage\n"
                "`/sondage-terminer <msg_id>` — Terminer un sondage"
            ),
            inline=False,
        )
        embed.add_field(
            name="Suggestions",
            value=(
                "`/suggestion configurer #salon` — Configurer le salon\n"
                "`/suggestion soumettre <texte>` — Soumettre une suggestion\n"
                "`/suggestion accepter <msg_id>` — Accepter (admin)\n"
                "`/suggestion refuser <msg_id>` — Refuser (admin)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Niveaux & XP",
            value=(
                "`/niveau voir [@membre]` — Voir son niveau\n"
                "`/classement` — Top 10 XP\n"
                "`/niveau configurer #salon` — Salon de level up (admin)\n"
                "`/niveau recompense-ajouter <n> @role` — Ajouter récompense\n"
                "`/niveau recompense-retirer <n>` — Retirer récompense\n"
                "`/niveau recompense-liste` — Voir les récompenses"
            ),
            inline=False,
        )
        embed.add_field(
            name="Économie",
            value=(
                "`/argent [@membre]` — Voir son solde\n"
                "`/daily` — Récompense quotidienne\n"
                "`/donner @membre <montant>` — Transférer de l'argent\n"
                "`/classement-argent` — Top 10 richesse\n"
                "`/inventaire [@membre]` — Voir son inventaire\n"
                "`/boutique liste` — Voir la boutique\n"
                "`/boutique ajouter/retirer/acheter` — Gérer les articles"
            ),
            inline=False,
        )
        embed.add_field(
            name="Giveaways",
            value=(
                "`/giveaway lancer #salon <durée_h> <prix>` — Lancer un giveaway\n"
                "`/giveaway terminer <msg_id>` — Terminer manuellement\n"
                "`/giveaway relancer <msg_id>` — Re-roll les gagnants\n"
                "`/giveaway liste` — Giveaways en cours"
            ),
            inline=False,
        )
        embed.add_field(
            name="Tickets",
            value=(
                "`/ticket configurer #catégorie @role` — Configurer les tickets\n"
                "`/ticket panel #salon` — Envoyer le bouton d'ouverture\n"
                "`/ticket fermer` — Fermer le ticket actuel\n"
                "`/ticket ajouter @membre` — Ajouter quelqu'un au ticket"
            ),
            inline=False,
        )
        embed.add_field(
            name="Messages planifiés",
            value=(
                "`/planifie creer <nom> #salon <message> <heures>` — Créer\n"
                "`/planifie supprimer <nom>` — Supprimer\n"
                "`/planifie liste` — Voir les messages planifiés"
            ),
            inline=False,
        )
        embed.add_field(
            name="Compteurs",
            value=(
                "`/compteur creer <type>` — Créer un compteur vocal (membres/bots/salons/boosts)\n"
                "`/compteur supprimer <type>` — Supprimer un compteur\n"
                "`/compteur liste` — Voir les compteurs actifs"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏎️ SimRacing — Temps au tour",
            value=(
                "`/temps enregistrer <voiture> <piste> <temps>` — Enregistrer un temps\n"
                "`/temps classement <voiture> <piste>` — Leaderboard\n"
                "`/temps personnel [@membre]` — Voir ses meilleurs temps\n"
                "`/temps supprimer <voiture> <piste>` — Supprimer son temps"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏎️ SimRacing — Sessions",
            value=(
                "`/session creer <titre> <date> <heure> <sim> <piste>` — Organiser une session\n"
                "`/session liste` — Prochaines sessions\n"
                "`/session info <id>` — Détails d'une session\n"
                "`/session annuler <id>` — Annuler une session\n"
                "`/session configurer #salon` — Salon des rappels (admin)"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏎️ SimRacing — Championnats",
            value=(
                "`/championnat creer <nom> <points>` — Créer un championnat\n"
                "`/championnat resultat <nom> <manche>` — Enregistrer les résultats\n"
                "`/championnat classement <nom>` — Voir le classement\n"
                "`/championnat calendrier <nom>` — Voir les manches\n"
                "`/championnat liste` — Tous les championnats\n"
                "`/incident signaler @pilote <raison>` — Signaler un incident\n"
                "`/incident penalite @pilote <type> <raison>` — Appliquer une pénalité"
            ),
            inline=False,
        )
        embed.set_footer(text="R2D12 • Beep boop !")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Affiche les informations du serveur")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(
            title=guild.name,
            color=discord.Color.blurple(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Propriétaire", value=guild.owner.mention if guild.owner else "Inconnu")
        embed.add_field(name="Membres", value=guild.member_count)
        embed.add_field(name="Salons", value=len(guild.channels))
        embed.add_field(name="Rôles", value=len(guild.roles))
        embed.add_field(name="Créé le", value=discord.utils.format_dt(guild.created_at, style="D"))
        embed.set_footer(text=f"ID : {guild.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Affiche les informations d'un membre")
    @app_commands.describe(membre="Le membre dont vous voulez voir les infos (vous par défaut)")
    async def userinfo(self, interaction: discord.Interaction, membre: discord.Member = None):
        membre = membre or interaction.user
        roles = [r.mention for r in membre.roles if r.name != "@everyone"]
        embed = discord.Embed(
            title=str(membre),
            color=membre.color,
        )
        embed.set_thumbnail(url=membre.display_avatar.url)
        embed.add_field(name="Pseudo", value=membre.display_name)
        embed.add_field(name="Compte créé le", value=discord.utils.format_dt(membre.created_at, style="D"))
        embed.add_field(name="A rejoint le", value=discord.utils.format_dt(membre.joined_at, style="D") if membre.joined_at else "Inconnu")
        embed.add_field(
            name=f"Rôles ({len(roles)})",
            value=" ".join(roles) if roles else "Aucun",
            inline=False,
        )
        embed.set_footer(text=f"ID : {membre.id}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
