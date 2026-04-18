import discord
from discord import app_commands
from discord.ext import commands


def parse_color(hex_str: str) -> discord.Color | None:
    hex_str = hex_str.strip().lstrip("#")
    try:
        return discord.Color(int(hex_str, 16))
    except ValueError:
        return None


class Roles(commands.Cog):
    """Création, suppression et modification de rôles."""

    role_group = app_commands.Group(name="role", description="Gestion des rôles du serveur")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

    @role_group.command(name="modifier", description="Modifier le nom ou la couleur d'un rôle")
    @app_commands.describe(
        role="Le rôle à modifier",
        nom="Nouveau nom (laisser vide pour conserver l'actuel)",
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
