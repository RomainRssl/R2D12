import discord
from discord import app_commands
from discord.ext import commands


def parse_color(hex_str: str) -> discord.Color | None:
    hex_str = hex_str.strip().lstrip("#")
    try:
        return discord.Color(int(hex_str, 16))
    except ValueError:
        return None


PERMISSIONS_LIST = [
    app_commands.Choice(name="Administrateur",            value="administrator"),
    app_commands.Choice(name="Gérer le serveur",          value="manage_guild"),
    app_commands.Choice(name="Gérer les salons",          value="manage_channels"),
    app_commands.Choice(name="Gérer les rôles",           value="manage_roles"),
    app_commands.Choice(name="Gérer les messages",        value="manage_messages"),
    app_commands.Choice(name="Expulser des membres",      value="kick_members"),
    app_commands.Choice(name="Bannir des membres",        value="ban_members"),
    app_commands.Choice(name="Exclure temporairement",    value="moderate_members"),
    app_commands.Choice(name="Mentionner @everyone",      value="mention_everyone"),
    app_commands.Choice(name="Envoyer des messages",      value="send_messages"),
    app_commands.Choice(name="Voir les salons",           value="view_channel"),
    app_commands.Choice(name="Intégrer des liens",        value="embed_links"),
    app_commands.Choice(name="Joindre des fichiers",      value="attach_files"),
    app_commands.Choice(name="Ajouter des réactions",     value="add_reactions"),
    app_commands.Choice(name="Emojis externes",           value="use_external_emojis"),
    app_commands.Choice(name="Se connecter (vocal)",      value="connect"),
    app_commands.Choice(name="Parler (vocal)",            value="speak"),
    app_commands.Choice(name="Rendre muet (vocal)",       value="mute_members"),
    app_commands.Choice(name="Mettre en sourdine",        value="deafen_members"),
    app_commands.Choice(name="Déplacer des membres",      value="move_members"),
    app_commands.Choice(name="Gérer les pseudos",         value="manage_nicknames"),
    app_commands.Choice(name="Changer son pseudo",        value="change_nickname"),
    app_commands.Choice(name="Gérer les webhooks",        value="manage_webhooks"),
    app_commands.Choice(name="Voir les logs d'audit",     value="view_audit_log"),
    app_commands.Choice(name="Créer des invitations",     value="create_instant_invite"),
]

PERM_LABELS = {c.value: c.name for c in PERMISSIONS_LIST}


class Roles(commands.Cog):
    """Création, suppression, modification de rôles et gestion des permissions."""

    role_group = app_commands.Group(name="role", description="Gestion des rôles du serveur")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Création ─────────────────────────────────────────────────────────────

    @role_group.command(name="creer", description="Créer un nouveau rôle")
    @app_commands.describe(
        nom="Nom du rôle",
        couleur="Couleur hexadécimale (ex: FF5733 ou #FF5733)",
        mentionnable="Le rôle peut être mentionné par tous",
        affiche_separe="Afficher le rôle séparément dans la liste des membres",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def role_create(
        self,
        interaction: discord.Interaction,
        nom: str,
        couleur: str = None,
        mentionnable: bool = False,
        affiche_separe: bool = False,
    ):
        color = discord.Color.default()
        if couleur:
            parsed = parse_color(couleur)
            if parsed is None:
                await interaction.response.send_message(
                    "Couleur invalide. Utilisez un code hexadécimal (ex: `FF5733` ou `#FF5733`).",
                    ephemeral=True,
                )
                return
            color = parsed

        try:
            role = await interaction.guild.create_role(
                name=nom,
                color=color,
                mentionable=mentionnable,
                hoist=affiche_separe,
                reason=f"Créé par {interaction.user} via /role creer",
            )
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de créer des rôles.", ephemeral=True)
            return

        embed = discord.Embed(title="✅ Rôle créé", color=role.color)
        embed.add_field(name="Nom", value=role.mention)
        embed.add_field(name="Couleur", value=str(role.color))
        embed.add_field(name="Mentionnable", value="Oui" if mentionnable else "Non")
        embed.add_field(name="Affiché séparément", value="Oui" if affiche_separe else "Non")
        embed.set_footer(text=f"ID : {role.id}")
        await interaction.response.send_message(embed=embed)

    # ── Suppression ───────────────────────────────────────────────────────────

    @role_group.command(name="supprimer", description="Supprimer un rôle du serveur")
    @app_commands.describe(role="Le rôle à supprimer")
    @app_commands.default_permissions(manage_roles=True)
    async def role_delete(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Je ne peux pas supprimer un rôle supérieur ou égal au mien.", ephemeral=True
            )
            return
        if role.is_default():
            await interaction.response.send_message("Impossible de supprimer le rôle @everyone.", ephemeral=True)
            return

        nom = role.name
        try:
            await role.delete(reason=f"Supprimé par {interaction.user} via /role supprimer")
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de supprimer ce rôle.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Rôle **{nom}** supprimé.", ephemeral=True)

    # ── Modification ──────────────────────────────────────────────────────────

    @role_group.command(name="modifier", description="Modifier le nom, la couleur ou les options d'un rôle")
    @app_commands.describe(
        role="Le rôle à modifier",
        nom="Nouveau nom",
        couleur="Nouvelle couleur hexadécimale (ex: FF5733)",
        mentionnable="Modifier si le rôle peut être mentionné",
        affiche_separe="Modifier l'affichage séparé dans la liste des membres",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def role_edit(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        nom: str = None,
        couleur: str = None,
        mentionnable: bool = None,
        affiche_separe: bool = None,
    ):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Je ne peux pas modifier un rôle supérieur ou égal au mien.", ephemeral=True
            )
            return

        kwargs = {}
        if nom:
            kwargs["name"] = nom
        if couleur:
            parsed = parse_color(couleur)
            if parsed is None:
                await interaction.response.send_message(
                    "Couleur invalide. Utilisez un code hexadécimal (ex: `FF5733`).", ephemeral=True
                )
                return
            kwargs["color"] = parsed
        if mentionnable is not None:
            kwargs["mentionable"] = mentionnable
        if affiche_separe is not None:
            kwargs["hoist"] = affiche_separe

        if not kwargs:
            await interaction.response.send_message("Aucune modification spécifiée.", ephemeral=True)
            return

        try:
            await role.edit(reason=f"Modifié par {interaction.user} via /role modifier", **kwargs)
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de modifier ce rôle.", ephemeral=True)
            return

        embed = discord.Embed(title="✅ Rôle modifié", color=role.color)
        embed.add_field(name="Rôle", value=role.mention)
        if nom:
            embed.add_field(name="Nouveau nom", value=nom)
        if couleur:
            embed.add_field(name="Nouvelle couleur", value=str(role.color))
        if mentionnable is not None:
            embed.add_field(name="Mentionnable", value="Oui" if mentionnable else "Non")
        if affiche_separe is not None:
            embed.add_field(name="Affiché séparément", value="Oui" if affiche_separe else "Non")
        await interaction.response.send_message(embed=embed)

    # ── Permissions ───────────────────────────────────────────────────────────

    @role_group.command(name="permissions-voir", description="Voir les permissions d'un rôle")
    @app_commands.describe(role="Le rôle dont voir les permissions")
    @app_commands.default_permissions(manage_roles=True)
    async def role_perms_view(self, interaction: discord.Interaction, role: discord.Role):
        perms = role.permissions
        granted = []
        denied = []
        for perm_value, label in PERM_LABELS.items():
            if getattr(perms, perm_value, False):
                granted.append(f"✅ {label}")
            else:
                denied.append(f"❌ {label}")

        embed = discord.Embed(
            title=f"Permissions — {role.name}",
            color=role.color,
        )
        if granted:
            embed.add_field(name="Accordées", value="\n".join(granted), inline=True)
        if denied:
            embed.add_field(name="Refusées", value="\n".join(denied), inline=True)
        embed.set_footer(text=f"ID : {role.id}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @role_group.command(name="permissions-ajouter", description="Accorder une permission à un rôle")
    @app_commands.describe(role="Le rôle à modifier", permission="La permission à accorder")
    @app_commands.choices(permission=PERMISSIONS_LIST)
    @app_commands.default_permissions(manage_roles=True)
    async def role_perms_add(self, interaction: discord.Interaction, role: discord.Role, permission: str):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Je ne peux pas modifier un rôle supérieur ou égal au mien.", ephemeral=True
            )
            return

        flag = discord.Permissions(**{permission: True})
        new_perms = discord.Permissions(role.permissions.value | flag.value)
        try:
            await role.edit(
                permissions=new_perms,
                reason=f"Permission '{permission}' accordée par {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de modifier ce rôle.", ephemeral=True)
            return

        label = PERM_LABELS.get(permission, permission)
        embed = discord.Embed(title="✅ Permission accordée", color=discord.Color.green())
        embed.add_field(name="Rôle", value=role.mention)
        embed.add_field(name="Permission", value=label)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @role_group.command(name="permissions-retirer", description="Retirer une permission d'un rôle")
    @app_commands.describe(role="Le rôle à modifier", permission="La permission à retirer")
    @app_commands.choices(permission=PERMISSIONS_LIST)
    @app_commands.default_permissions(manage_roles=True)
    async def role_perms_remove(self, interaction: discord.Interaction, role: discord.Role, permission: str):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Je ne peux pas modifier un rôle supérieur ou égal au mien.", ephemeral=True
            )
            return

        flag = discord.Permissions(**{permission: True})
        new_perms = discord.Permissions(role.permissions.value & ~flag.value)
        try:
            await role.edit(
                permissions=new_perms,
                reason=f"Permission '{permission}' retirée par {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas la permission de modifier ce rôle.", ephemeral=True)
            return

        label = PERM_LABELS.get(permission, permission)
        embed = discord.Embed(title="❌ Permission retirée", color=discord.Color.red())
        embed.add_field(name="Rôle", value=role.mention)
        embed.add_field(name="Permission", value=label)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Liste ─────────────────────────────────────────────────────────────────

    @role_group.command(name="liste", description="Voir tous les rôles du serveur")
    async def role_list(self, interaction: discord.Interaction):
        roles = [r for r in reversed(interaction.guild.roles) if r.name != "@everyone"]
        if not roles:
            await interaction.response.send_message("Aucun rôle sur ce serveur.", ephemeral=True)
            return

        lines = [f"{r.mention} — `{r.id}`" for r in roles[:50]]
        embed = discord.Embed(
            title=f"Rôles du serveur ({len(roles)})",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        if len(roles) > 50:
            embed.set_footer(text=f"Affichage limité aux 50 premiers rôles sur {len(roles)}.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
