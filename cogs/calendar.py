import os
import json
import re
import unicodedata
import logging
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("RACES_SITE_URL", "https://paramourduspin.fun")
RACES_CHANNEL_ID = int(os.getenv("RACES_CHANNEL_ID", "0"))
RACES_CATEGORY_ID = int(os.getenv("RACES_CATEGORY_ID", "1399427481945247817"))
RACES_STAFF_ROLE_ID = int(os.getenv("RACES_STAFF_ROLE_ID", "1424791316881211412"))
DATA_FILE = "data/known_races.json"
DATA_MESSAGES = "data/race_messages.json"
DATA_REGISTRATIONS = "data/race_registrations.json"
PARIS = ZoneInfo("Europe/Paris")
TAG_SIMULATOR = "text-blue-400"   # simulateur (Le Mans ultimate, iRacing…)
TAG_CIRCUIT   = "text-green-400"   # circuit (Spa, Le Mans…)
TAG_CLASSES   = "text-orange-400"  # classes voiture (LMGT3, Hypercar…)
TAG_COLORS = (TAG_SIMULATOR, TAG_CIRCUIT, TAG_CLASSES)  # rétrocompat


# Mapping classe → (ButtonStyle, emoji)
# Discord n'a que 4 couleurs : success=vert, danger=rouge, primary=bleu, secondary=gris
CLASS_STYLES: dict = {
    "lmgt3":    (discord.ButtonStyle.success,   "🟢"),
    "hypercar": (discord.ButtonStyle.danger,    "🔴"),
    "lmp2":     (discord.ButtonStyle.primary,   "🔵"),
    "lmp3":     (discord.ButtonStyle.secondary, "🟣"),
    "gte":      (discord.ButtonStyle.secondary, "🟡"),
}

def _class_style(name: str):
    """Retourne (ButtonStyle, emoji) pour une classe donnée."""
    key = name.lower().replace(" ", "")
    _, emoji = CLASS_STYLES.get(key, (None, "🏎️"))
    return discord.ButtonStyle.secondary, emoji


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _clean_class_name(name: str) -> str:
    """Retire les suffixes parasites comme '(toute classe)'."""
    name = re.sub(r"\(.*?\)", "", name).strip()
    return name


# ── Helpers registrations (standalone pour les callbacks) ────────

def _load_registrations() -> dict:
    try:
        with open(DATA_REGISTRATIONS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_registrations(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DATA_REGISTRATIONS, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _build_class_embed(title: str, classes_data: dict) -> discord.Embed:
    """Construit l'embed de sélection de classe style Apollo."""
    total = sum(len(v) for v in classes_data.values())
    embed = discord.Embed(
        title=f"🏁 {title}",
        description=(
            "Choisissez votre classe en cliquant sur le bouton correspondant.\n"
            "Cliquez à nouveau sur votre classe pour vous désinscrire."
        ),
        color=0xE63946,
    )
    for class_name, members in classes_data.items():
        count = len(members)
        if members:
            value = "\n".join(f"• {m['name']}" for m in members)
        else:
            value = "*Aucun inscrit*"
        embed.add_field(
            name=f"🏎️ {class_name} ({count})",
            value=value,
            inline=True,
        )
    embed.set_footer(text=f"Par amour du spin · {total} pilote(s) inscrit(s)")
    return embed


# ── Bouton classe ─────────────────────────────────────────────────

class ClassButton(discord.ui.Button):
    def __init__(self, class_name: str, channel_id: int):
        style, emoji = _class_style(class_name)
        super().__init__(
            label=class_name[:80],
            style=style,
            emoji=emoji,
            custom_id=f"cls_{channel_id}_{_slugify(class_name)}",
        )
        self.class_name = class_name
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction):
        regs = _load_registrations()
        key = str(self.channel_id)

        if key not in regs:
            await interaction.response.send_message(
                "Données de course introuvables.", ephemeral=True
            )
            return

        data = regs[key]
        uid = str(interaction.user.id)

        # Vérifier si déjà dans cette classe
        already_here = any(
            m["id"] == uid for m in data["classes"].get(self.class_name, [])
        )

        # Retirer de toutes les classes
        for cls in data["classes"]:
            data["classes"][cls] = [
                m for m in data["classes"][cls] if m["id"] != uid
            ]

        if already_here:
            # Désinscription
            msg_text = f"❌ Vous avez été désinscrit de **{self.class_name}**."
        else:
            # Inscription dans la nouvelle classe
            if self.class_name not in data["classes"]:
                data["classes"][self.class_name] = []
            data["classes"][self.class_name].append(
                {"id": uid, "name": interaction.user.display_name}
            )
            msg_text = f"✅ Inscrit en **{self.class_name}** !"

        _save_registrations(regs)

        # Mettre à jour le message dans le channel
        try:
            channel = interaction.guild.get_channel(self.channel_id)
            if channel and data.get("message_id"):
                msg = await channel.fetch_message(int(data["message_id"]))
                await msg.edit(
                    embed=_build_class_embed(data["title"], data["classes"])
                )
        except Exception as e:
            logger.warning("Impossible de mettre à jour le message de classe : %s", e)

        await interaction.response.send_message(msg_text, ephemeral=True)


class ClassRegistrationView(discord.ui.View):
    def __init__(self, class_names: list, channel_id: int):
        super().__init__(timeout=None)
        for name in class_names[:5]:
            self.add_item(ClassButton(name, channel_id))


# ── Bouton inscription simple ─────────────────────────────────────

class RaceButton(discord.ui.Button):
    def __init__(self, race_title: str, role_id: int):
        super().__init__(
            label=f"Inscription {race_title}",
            style=discord.ButtonStyle.primary,
            custom_id=f"race_register_{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Rôle introuvable.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(
                f"❌ Désinscrit de **{role.name}**.", ephemeral=True
            )
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                f"✅ Inscrit pour **{role.name}** !", ephemeral=True
            )


class RaceRegistrationView(discord.ui.View):
    def __init__(self, race_title: str, role_id: int):
        super().__init__(timeout=None)
        self.add_item(RaceButton(race_title, role_id))


# ── Cog principal ─────────────────────────────────────────────────

class Calendar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_new_races.start()
        self.check_race_reminders.start()

    def cog_unload(self):
        self.check_new_races.cancel()
        self.check_race_reminders.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # Restaurer les boutons d'inscription simples
        for msg_id, data in self._load_messages().items():
            view = RaceRegistrationView(data["title"], data["role_id"])
            self.bot.add_view(view, message_id=int(msg_id))

        # Restaurer les vues de sélection de classe
        for key, data in _load_registrations().items():
            classes = list(data.get("classes", {}).keys())
            if classes and data.get("message_id"):
                view = ClassRegistrationView(classes, int(key))
                self.bot.add_view(view, message_id=int(data["message_id"]))

    # ── Known races ───────────────────────────────────────────────

    def _load_known(self) -> set | None:
        try:
            with open(DATA_FILE) as f:
                return set(json.load(f).get("known_ids", []))
        except FileNotFoundError:
            return None

    def _save_known(self, ids: set):
        with open(DATA_FILE, "w") as f:
            json.dump({"known_ids": list(ids)}, f)

    # ── Message mapping ───────────────────────────────────────────

    def _load_messages(self) -> dict:
        try:
            with open(DATA_MESSAGES) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save_message(self, message_id: str, data: dict):
        messages = self._load_messages()
        messages[message_id] = data
        with open(DATA_MESSAGES, "w") as f:
            json.dump(messages, f)

    # ── API /api/events ───────────────────────────────────────────

    async def _fetch_races_api(self) -> list:
        """Récupère les courses depuis l'API /api/events (inclut serverName et serverPassword)."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{SITE_URL}/api/events",
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"Accept": "application/json"},
                ) as r:
                    if r.status != 200:
                        logger.error("API /api/events — statut %s", r.status)
                        return []
                    data = await r.json()

            races = []
            for event in data:
                # cars est un JSON string dans l'API
                try:
                    cars_raw = json.loads(event.get("cars") or "[]")
                except (json.JSONDecodeError, TypeError):
                    cars_raw = []
                classes = [_clean_class_name(c) for c in cars_raw if c]

                image = event.get("imageUrl") or ""
                if image and not image.startswith("http"):
                    image = f"{SITE_URL}{image}"

                desc = event.get("description") or ""
                if len(desc) > 4096:
                    desc = desc[:4093] + "…"

                races.append({
                    "id":          event["date"],        # datetime comme ID (continuité)
                    "title":       event["title"],
                    "date":        event["date"],
                    "simulator":   event.get("game", "") or "",
                    "circuit":     event.get("track", "") or "",
                    "classes":     classes,
                    "description": desc,
                    "image":       image,
                    "server_name": event.get("serverName", "") or "",
                    "password":    event.get("serverPassword", "") or "",
                })
            logger.info("API /api/events : %d course(s) récupérée(s)", len(races))
            return races

        except Exception as e:
            logger.error("Erreur API /api/events : %s", e)
            return []

    # ── Annonce ───────────────────────────────────────────────────

    async def _announce_race(self, race: dict):
        try:
            channel = await self.bot.fetch_channel(RACES_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden) as e:
            logger.error("Impossible de trouver le channel %s : %s", RACES_CHANNEL_ID, e)
            return

        guild = channel.guild
        role = await guild.create_role(name=race["title"], mentionable=True)

        category = guild.get_channel(RACES_CATEGORY_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        staff_role = guild.get_role(RACES_STAFF_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
        race_channel = await guild.create_text_channel(
            name=_slugify(race["title"]),
            category=category,
            overwrites=overwrites,
        )

        # Annonce dans le channel principal
        view = RaceRegistrationView(race["title"], role.id)
        msg = await channel.send(embed=self._build_embed(race, race_channel), view=view)

        self._save_message(str(msg.id), {
            "role_id": role.id,
            "channel_id": race_channel.id,
            "title": race["title"],
            "date": race["date"],
            "server_name": race.get("server_name", ""),
            "password": race.get("password", ""),
            "notified_1h": False,
        })

        # Premier message du channel privé : infos de la course (sans bouton d'inscription)
        await race_channel.send(embed=self._build_embed(race))

        # Sélection de classe dans le channel privé (si multiclasse)
        classes = race.get("classes", [])
        if len(classes) >= 2:
            await self._post_class_selection(race_channel, race, classes)

    async def _post_class_selection(
        self,
        channel: discord.TextChannel,
        race: dict,
        classes: list,
    ):
        """Poste le message de sélection de classe dans le channel privé de la course."""
        classes = [c for c in classes if c][:5]
        classes_data = {c: [] for c in classes}
        view = ClassRegistrationView(classes, channel.id)
        msg = await channel.send(
            embed=_build_class_embed(race["title"], classes_data),
            view=view,
        )
        regs = _load_registrations()
        regs[str(channel.id)] = {
            "title": race["title"],
            "message_id": str(msg.id),
            "classes": classes_data,
        }
        _save_registrations(regs)

    # ── Tâche planifiée ───────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def check_new_races(self):
        if not RACES_CHANNEL_ID:
            return

        races = await self._fetch_races_api()
        if not races:
            return

        known = self._load_known()
        current_ids = {r["id"] for r in races}

        if known is None:
            self._save_known(current_ids)
            return

        new_races = [r for r in races if r["id"] not in known]
        if not new_races:
            return

        for race in new_races:
            try:
                await self._announce_race(race)
            except Exception as e:
                logger.error("Erreur lors de l'annonce de '%s' : %s", race.get("title"), e)
                continue
            known.add(race["id"])

        self._save_known(known)

    @check_new_races.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ── Rappel 1h avant la course ─────────────────────────────────

    @tasks.loop(minutes=1)
    async def check_race_reminders(self):
        """Envoie les infos serveur/MDP dans le channel privé 1h avant chaque course."""
        now = datetime.now(PARIS)
        messages = self._load_messages()
        updated = False

        # Charger les données API une seule fois pour enrichir les entrées manquantes
        api_races: list | None = None

        for msg_id, data in messages.items():
            if data.get("notified_1h"):
                continue
            if not data.get("date") or not data.get("channel_id"):
                continue

            # Si server_name/password manquent, tenter de les récupérer depuis l'API
            if not data.get("server_name") and not data.get("password"):
                if api_races is None:
                    api_races = await self._fetch_races_api()
                match = next((r for r in api_races if r["id"] == data.get("date")), None)
                if match:
                    data["server_name"] = match.get("server_name", "")
                    data["password"]    = match.get("password", "")
                    updated = True

            # Toujours passer si aucune info serveur disponible
            if not data.get("server_name") and not data.get("password"):
                continue

            try:
                race_dt = datetime.fromisoformat(
                    data["date"].replace("Z", "+00:00")
                ).astimezone(PARIS)
            except ValueError:
                continue

            delta = race_dt - now
            # Fenêtre : entre 55 et 65 minutes avant le départ
            if not (timedelta(minutes=55) <= delta <= timedelta(minutes=65)):
                continue

            try:
                channel = await self.bot.fetch_channel(int(data["channel_id"]))
            except Exception as e:
                logger.warning("Rappel 1h — channel introuvable (%s) : %s", data["channel_id"], e)
                data["notified_1h"] = True   # éviter de réessayer indéfiniment
                updated = True
                continue

            embed = discord.Embed(
                title=f"🚦 Départ dans 1 heure — {data['title']}",
                color=0xE63946,
            )
            if data.get("server_name"):
                embed.add_field(name="🖥️ Nom du serveur", value=data["server_name"], inline=False)
            if data.get("password"):
                embed.add_field(name="🔒 Mot de passe", value=data["password"], inline=False)
            embed.set_footer(text="Par amour du spin")

            try:
                await channel.send(embed=embed)
                logger.info("Rappel 1h envoyé pour '%s'", data["title"])
            except Exception as e:
                logger.error("Rappel 1h — impossible d'envoyer dans %s : %s", data["channel_id"], e)

            data["notified_1h"] = True
            updated = True

        if updated:
            with open(DATA_MESSAGES, "w") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)

    @check_race_reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()

    # ── Commandes admin ───────────────────────────────────────────

    def _is_admin(self, user: discord.Member) -> bool:
        return user.guild_permissions.administrator or any(
            r.id == RACES_STAFF_ROLE_ID for r in user.roles
        )

    @discord.app_commands.command(
        name="coursediag",
        description="Diagnostique le système d'annonces de courses",
    )
    async def course_diagnostic(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        lines = []

        lines.append(f"**RACES_CHANNEL_ID** : `{RACES_CHANNEL_ID}`")
        if RACES_CHANNEL_ID:
            try:
                ch = await self.bot.fetch_channel(RACES_CHANNEL_ID)
                lines.append(f"Channel trouvé : {ch.mention}")
            except Exception as e:
                lines.append(f"Channel **introuvable** : {e}")
        else:
            lines.append("Channel **non configuré** — définir `RACES_CHANNEL_ID` dans `.env`")

        lines.append(f"\n**API** : `{SITE_URL}/api/events`")
        try:
            races = await self._fetch_races_api()
            if races:
                lines.append(f"API accessible — {len(races)} course(s) trouvée(s)")
                known = self._load_known() or set()
                new = [r for r in races if r["id"] not in known]
                lines.append(f"Courses connues : {len(known)} | Nouvelles : **{len(new)}**")
                for r in races:
                    status = "✅ connue" if r["id"] in known else "🆕 nouvelle"
                    lines.append(f"  • **{r['title']}** — {status}")
                    lines.append(f"    🎮 {r.get('simulator') or '—'}  🏟️ {r.get('circuit') or '—'}")
                    classes_str = ", ".join(r["classes"]) if r["classes"] else "*aucune*"
                    lines.append(f"    🏎️ Classes : {classes_str}")
                    if r.get("server_name"):
                        lines.append(f"    🖥️ Serveur : {r['server_name']}")
            else:
                lines.append("API **inaccessible** ou aucune course")
        except Exception as e:
            lines.append(f"Erreur : {e}")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @discord.app_commands.command(
        name="coursereset",
        description="Réinitialise la liste des courses connues (force les annonces)",
    )
    async def course_reset(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
            await interaction.response.send_message(
                "Liste réinitialisée. Au prochain scan (≤5 min), toutes les courses actuelles seront annoncées.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Aucun fichier de courses connues trouvé.", ephemeral=True
            )

    @discord.app_commands.command(
        name="courseforcer",
        description="Force l'annonce immédiate des courses non encore annoncées",
    )
    async def course_forcer(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        if not RACES_CHANNEL_ID:
            await interaction.followup.send("RACES_CHANNEL_ID non configuré.", ephemeral=True)
            return
        races = await self._fetch_races_api()
        if not races:
            await interaction.followup.send("API inaccessible ou aucune course.", ephemeral=True)
            return

        known = self._load_known() or set()
        new_races = [r for r in races if r["id"] not in known]

        if not new_races:
            await interaction.followup.send("Aucune nouvelle course à annoncer.", ephemeral=True)
            return

        count = 0
        for race in new_races:
            try:
                await self._announce_race(race)
                known.add(race["id"])
                count += 1
            except Exception as e:
                logger.error("Erreur annonce forcée '%s' : %s", race.get("title"), e)

        self._save_known(known)
        await interaction.followup.send(f"{count} course(s) annoncée(s).", ephemeral=True)

    @discord.app_commands.command(
        name="coursemdp",
        description="Envoie immédiatement les infos serveur/MDP dans le channel privé d'une course",
    )
    async def course_mdp(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user):
            await interaction.response.send_message(
                "Commande réservée aux administrateurs.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        races_api = await self._fetch_races_api()
        api_by_date = {r["id"]: r for r in races_api}

        messages = self._load_messages()
        sent = 0
        skipped = 0

        for msg_id, data in messages.items():
            if data.get("notified_1h") or not data.get("channel_id"):
                continue

            # Enrichir depuis l'API si besoin
            date_key = data.get("date", "")
            if (not data.get("server_name") and not data.get("password")) and date_key in api_by_date:
                api_r = api_by_date[date_key]
                data["server_name"] = api_r.get("server_name", "")
                data["password"]    = api_r.get("password", "")

            if not data.get("server_name") and not data.get("password"):
                skipped += 1
                continue

            try:
                channel = await self.bot.fetch_channel(int(data["channel_id"]))
                embed = discord.Embed(
                    title=f"🚦 Infos serveur — {data['title']}",
                    color=0xE63946,
                )
                if data.get("server_name"):
                    embed.add_field(name="🖥️ Nom du serveur", value=data["server_name"], inline=False)
                if data.get("password"):
                    embed.add_field(name="🔒 Mot de passe", value=data["password"], inline=False)
                embed.set_footer(text="Par amour du spin")
                await channel.send(embed=embed)
                data["notified_1h"] = True
                sent += 1
            except Exception as e:
                logger.error("coursemdp — erreur channel %s : %s", data["channel_id"], e)
                skipped += 1

        with open(DATA_MESSAGES, "w") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

        await interaction.followup.send(
            f"✅ {sent} message(s) envoyé(s){f', {skipped} ignoré(s) (pas de données)' if skipped else ''}.",
            ephemeral=True,
        )

    # ── Embed annonce principale ──────────────────────────────────

    def _build_embed(self, race: dict, race_channel=None) -> discord.Embed:
        dt = datetime.fromisoformat(race["date"].replace("Z", "+00:00")).astimezone(PARIS)
        date_str = dt.strftime("%A %d %B %Y à %H:%M").capitalize()
        description = race.get("description") or ""
        # Discord limite les descriptions d'embed à 4096 caractères
        if len(description) > 4096:
            description = description[:4093] + "…"
        embed = discord.Embed(
            title=f"🏁 Nouvelle course : {race['title']}",
            description=description or None,
            color=0xE63946,
            url=race.get("url") or SITE_URL,
        )
        embed.add_field(name="📅 Date", value=date_str, inline=False)
        if race.get("simulator"):
            embed.add_field(name="🎮 Simulateur", value=race["simulator"], inline=True)
        if race.get("circuit"):
            embed.add_field(name="🏟️ Circuit", value=race["circuit"], inline=True)
        if race.get("classes"):
            embed.add_field(
                name="🏎️ Classes",
                value=" · ".join(race["classes"]),
                inline=False,
            )
        if race_channel:
            embed.add_field(name="💬 Salon", value=race_channel.mention, inline=False)
        if race.get("image"):
            embed.set_image(url=race["image"])
        embed.set_footer(text="Par amour du spin")
        return embed


async def setup(bot):
    await bot.add_cog(Calendar(bot))
