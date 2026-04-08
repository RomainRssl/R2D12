import json
import os
import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

POLLS_FILE = "data/polls.json"


def load_data() -> dict:
    if not os.path.exists(POLLS_FILE):
        return {}
    with open(POLLS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(POLLS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_poll_embed(poll: dict, closed: bool = False) -> discord.Embed:
    total = len(poll["votes"])
    options = poll["options"]
    counts = [0] * len(options)
    for opt_idx in poll["votes"].values():
        if 0 <= opt_idx < len(options):
            counts[opt_idx] += 1

    embed = discord.Embed(
        title=("📊 " if not closed else "📊 [TERMINÉ] ") + poll["question"],
        color=discord.Color.blurple() if not closed else discord.Color.greyple(),
    )
    for i, (opt, count) in enumerate(zip(options, counts)):
        pct = round(count / total * 100) if total > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        embed.add_field(name=f"{opt}", value=f"`{bar}` {pct}% ({count} vote(s))", inline=False)

    ends_at = datetime.datetime.fromisoformat(poll["ends_at"])
    if closed:
        embed.set_footer(text=f"Sondage terminé • {total} vote(s) au total")
    else:
        embed.set_footer(text=f"Votes : {total} • Se termine {discord.utils.format_dt(ends_at, style='R')}")
    return embed


class PollView(discord.ui.View):
    def __init__(self, guild_id: str, message_id: str, options: list[str]):
        super().__init__(timeout=None)
        for i, opt in enumerate(options[:5]):
            btn = discord.ui.Button(
                label=opt[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"poll:{guild_id}:{message_id}:{i}",
            )
            btn.callback = self._make_callback(i, guild_id, message_id)
            self.add_item(btn)

    def _make_callback(self, opt_idx: int, guild_id: str, message_id: str):
        async def callback(interaction: discord.Interaction):
            data = load_data()
            poll = data.get(guild_id, {}).get(message_id)
            if not poll or poll.get("closed"):
                await interaction.response.send_message("Ce sondage est terminé.", ephemeral=True)
                return
            user_key = str(interaction.user.id)
            if user_key in poll["votes"]:
                if poll["votes"][user_key] == opt_idx:
                    await interaction.response.send_message("Vous avez déjà voté pour cette option.", ephemeral=True)
                    return
            poll["votes"][user_key] = opt_idx
            save_data(data)
            embed = build_poll_embed(poll)
            await interaction.response.edit_message(embed=embed)
        return callback


class Polls(commands.Cog):
    """Système de sondages avec boutons."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_polls.start()

    def cog_unload(self):
        self.check_polls.cancel()

    async def cog_load(self):
        """Recharge les vues persistantes."""
        data = load_data()
        for guild_id, polls in data.items():
            for msg_id, poll in polls.items():
                if not poll.get("closed"):
                    self.bot.add_view(PollView(guild_id, msg_id, poll["options"]))

    @tasks.loop(minutes=1)
    async def check_polls(self):
        data = load_data()
        now = datetime.datetime.utcnow()
        changed = False
        for guild_id, polls in data.items():
            for msg_id, poll in polls.items():
                if poll.get("closed"):
                    continue
                ends_at = datetime.datetime.fromisoformat(poll["ends_at"])
                if now >= ends_at:
                    poll["closed"] = True
                    changed = True
                    guild = self.bot.get_guild(int(guild_id))
                    if guild:
                        channel = guild.get_channel(poll["channel_id"])
                        if channel:
                            try:
                                msg = await channel.fetch_message(int(msg_id))
                                embed = build_poll_embed(poll, closed=True)
                                await msg.edit(embed=embed, view=None)
                            except (discord.NotFound, discord.Forbidden):
                                pass
        if changed:
            save_data(data)

    @check_polls.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="sondage", description="Créer un sondage avec boutons")
    @app_commands.describe(
        question="La question du sondage",
        option1="Option 1", option2="Option 2",
        option3="Option 3 (optionnel)", option4="Option 4 (optionnel)", option5="Option 5 (optionnel)",
        duree_heures="Durée en heures (défaut : 24)",
    )
    async def poll_create(
        self, interaction: discord.Interaction,
        question: str, option1: str, option2: str,
        option3: str = None, option4: str = None, option5: str = None,
        duree_heures: app_commands.Range[int, 1, 720] = 24,
    ):
        options = [o for o in [option1, option2, option3, option4, option5] if o]
        ends_at = datetime.datetime.utcnow() + datetime.timedelta(hours=duree_heures)

        await interaction.response.defer()
        msg = await interaction.followup.send(embed=discord.Embed(title="Création..."))

        poll = {
            "channel_id": interaction.channel_id,
            "question": question,
            "options": options,
            "votes": {},
            "ends_at": ends_at.isoformat(),
            "closed": False,
        }
        data = load_data()
        guild_key = str(interaction.guild_id)
        data.setdefault(guild_key, {})[str(msg.id)] = poll
        save_data(data)

        view = PollView(guild_key, str(msg.id), options)
        self.bot.add_view(view)
        embed = build_poll_embed(poll)
        await msg.edit(embed=embed, view=view)

    @app_commands.command(name="sondage-terminer", description="Terminer un sondage manuellement")
    @app_commands.describe(message_id="ID du message du sondage")
    @app_commands.default_permissions(manage_messages=True)
    async def poll_end(self, interaction: discord.Interaction, message_id: str):
        data = load_data()
        poll = data.get(str(interaction.guild_id), {}).get(message_id)
        if not poll:
            await interaction.response.send_message("Sondage introuvable.", ephemeral=True)
            return
        if poll.get("closed"):
            await interaction.response.send_message("Ce sondage est déjà terminé.", ephemeral=True)
            return
        poll["closed"] = True
        save_data(data)
        try:
            msg = await interaction.channel.fetch_message(int(message_id))
            await msg.edit(embed=build_poll_embed(poll, closed=True), view=None)
        except (discord.NotFound, discord.Forbidden):
            pass
        await interaction.response.send_message("Sondage terminé.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Polls(bot))
