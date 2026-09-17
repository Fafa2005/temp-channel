import discord
from discord import app_commands
from discord.ext import commands
import os
import sys
import json
import re
import unicodedata
import datetime

# ============================================
#  CONFIGURATION PAR DÉFAUT (utilisée tant qu'un serveur n'a rien configuré)
# ============================================
TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip().strip('"').strip("'")

DEFAULT_TRIGGER_CHANNEL_NAME = "➕ Créer un salon"  # utilisé seulement si aucun salon n'est configuré via /config
PRESETS_FILE = "presets.json"
CONFIG_FILE = "config.json"

# Liste de départ, volontairement courte et générique. Ajoute tes propres mots
# avec /config moderation ajouter_mot — notamment toute insulte ou terme
# discriminatoire spécifique à ta communauté que tu veux bloquer.
DEFAULT_BANNED_WORDS = [
    "connard", "connasse", "encule", "enculé", "salope", "pute", "batard",
    "bâtard", "abruti", "debile", "débile", "pd", "merde", "putain",
]

LINK_REGEX = re.compile(r"(https?://\S+|www\.\S+|discord\.gg/\S+)", re.IGNORECASE)

# ============================================
#  SETUP DU BOT
# ============================================
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.message_content = True  # nécessaire pour lire le contenu des messages (filtre anti-injures/liens)

bot = commands.Bot(command_prefix="!", intents=intents)


# ============================================
#  CONFIGURATION PAR SERVEUR (modifiable via les commandes /config)
# ============================================
def load_configs() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_configs():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f)


configs = load_configs()


def get_config(guild_id: int) -> dict:
    """Récupère (en la créant si besoin) la config d'un serveur, avec valeurs par défaut."""
    gid = str(guild_id)
    if gid not in configs:
        configs[gid] = {}
    cfg = configs[gid]
    # Réglages salons temporaires
    cfg.setdefault("trigger_channel_id", None)
    cfg.setdefault("category_id", None)
    cfg.setdefault("prefix", "🔊")
    cfg.setdefault("default_mode", "open")
    # Réglages modération automatique
    cfg.setdefault("mod_filter_links", True)
    cfg.setdefault("mod_filter_insults", True)
    cfg.setdefault("mod_timeout_minutes", 10)
    cfg.setdefault("mod_banned_words", list(DEFAULT_BANNED_WORDS))
    cfg.setdefault("mod_exempt_role_id", None)
    cfg.setdefault("mod_allowed_link_channel_ids", [])
    # Rôle requis pour voir/rejoindre les salons temporaires (ex: rôle "Membre")
    cfg.setdefault("visible_role_id", None)
    return cfg

# temp_channels[channel_id] = {
#   "owner_id": int, "panel_message_id": int,
#   "mode": "open" | "closed" | "private",
#   "whitelist": set[int], "blacklist": set[int],
#   "mic_allowed": bool, "video_allowed": bool, "soundboard_allowed": bool,
# }
temp_channels = {}


def default_data(owner_id: int, guild_id: int) -> dict:
    preset = presets.get(str(owner_id), {})
    cfg = get_config(guild_id)
    return {
        "owner_id": owner_id,
        "panel_message_id": None,
        "mode": preset.get("mode", cfg["default_mode"]),
        "whitelist": set(),
        "blacklist": set(),
        "mic_allowed": preset.get("mic_allowed", True),
        "video_allowed": preset.get("video_allowed", True),
        "soundboard_allowed": preset.get("soundboard_allowed", True),
    }


def load_presets() -> dict:
    if os.path.exists(PRESETS_FILE):
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_presets():
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f)


presets = load_presets()


# ============================================
#  APPLICATION DES PERMISSIONS
# ============================================
async def apply_permissions(channel: discord.VoiceChannel, data: dict):
    guild = channel.guild
    everyone = guild.default_role
    cfg = get_config(guild.id)

    if data["mode"] == "open":
        base_ow = discord.PermissionOverwrite(view_channel=True, connect=True)
    elif data["mode"] == "closed":
        base_ow = discord.PermissionOverwrite(view_channel=True, connect=False)
    else:  # private
        base_ow = discord.PermissionOverwrite(view_channel=False, connect=False)

    base_ow.speak = False if not data["mic_allowed"] else None
    base_ow.stream = False if not data["video_allowed"] else None
    base_ow.use_soundboard = False if not data["soundboard_allowed"] else None

    # Rôle "membre" : si configuré, seul ce rôle (en plus du propriétaire/whitelist)
    # voit et peut rejoindre le salon — @everyone n'a aucun accès.
    visible_role = guild.get_role(cfg["visible_role_id"]) if cfg["visible_role_id"] else None

    if visible_role:
        overwrites = {
            everyone: discord.PermissionOverwrite(view_channel=False, connect=False),
            visible_role: base_ow,
        }
    else:
        overwrites = {everyone: base_ow}

    owner = guild.get_member(data["owner_id"])
    if owner:
        overwrites[owner] = discord.PermissionOverwrite(
            view_channel=True, connect=True, manage_channels=True,
            move_members=True, mute_members=True, deafen_members=True,
        )

    for uid in data["whitelist"]:
        member = guild.get_member(uid)
        if member:
            overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True)

    for uid in data["blacklist"]:
        member = guild.get_member(uid)
        if member:
            overwrites[member] = discord.PermissionOverwrite(view_channel=False, connect=False)

    await channel.edit(overwrites=overwrites)


def mention_list(guild: discord.Guild, ids: set) -> str:
    if not ids:
        return "Aucun"
    names = []
    for uid in ids:
        member = guild.get_member(uid)
        names.append(member.mention if member else f"`{uid}`")
    return ", ".join(names)


def build_embed(channel: discord.VoiceChannel, data: dict) -> discord.Embed:
    owner = channel.guild.get_member(data["owner_id"])
    embed = discord.Embed(
        title=f"Salon de {owner.display_name if owner else 'Inconnu'}",
        description=(
            "Voici l'espace de configuration de votre salon vocal temporaire. "
            "Les différentes options disponibles vous permettent de personnaliser "
            "les permissions de votre salon selon vos préférences."
        ),
        color=discord.Color.dark_theme(),
    )
    embed.add_field(name="🔊 Ouvert", value="Le salon sera ouvert à tous, sauf ceux figurant sur la liste noire.", inline=True)
    embed.add_field(name="🔒 Fermé", value="Le salon sera visible de tous, mais accessible à la liste blanche.", inline=True)
    embed.add_field(name="🔐 Privé", value="Le salon ne sera visible et accessible qu'aux membres de la liste blanche.", inline=True)
    embed.add_field(name="✅ Liste blanche", value=mention_list(channel.guild, data["whitelist"]), inline=True)
    embed.add_field(name="⛔ Liste noire", value=mention_list(channel.guild, data["blacklist"]), inline=True)
    mode_label = {"open": "🔊 Ouvert", "closed": "🔒 Fermé", "private": "🔐 Privé"}[data["mode"]]
    embed.add_field(
        name="État actuel",
        value=f"{mode_label} • 🎙️ Micro: {'✅' if data['mic_allowed'] else '❌'} "
              f"• 🎥 Vidéo: {'✅' if data['video_allowed'] else '❌'} "
              f"• 🔉 Soundboards: {'✅' if data['soundboard_allowed'] else '❌'}",
        inline=False,
    )
    return embed


async def refresh_panel(channel: discord.VoiceChannel, data: dict):
    if not data["panel_message_id"]:
        return
    try:
        msg = await channel.fetch_message(data["panel_message_id"])
        await msg.edit(embed=build_embed(channel, data), view=ControlPanelView(channel.id))
    except discord.NotFound:
        pass


# ============================================
#  MODALS
# ============================================
class SettingsModal(discord.ui.Modal, title="Réglages du salon"):
    def __init__(self, channel: discord.VoiceChannel, data: dict):
        super().__init__()
        self.channel = channel
        self.data = data
        self.nom = discord.ui.TextInput(
            label="Nom du salon", default=channel.name, required=False, max_length=90
        )
        self.limite = discord.ui.TextInput(
            label="Limite de membres (0 = illimité)",
            default=str(channel.user_limit), required=False, max_length=3,
        )
        self.add_item(self.nom)
        self.add_item(self.limite)

    async def on_submit(self, interaction: discord.Interaction):
        kwargs = {}
        if self.nom.value:
            kwargs["name"] = self.nom.value
        if self.limite.value.isdigit():
            kwargs["user_limit"] = int(self.limite.value)
        if kwargs:
            await self.channel.edit(**kwargs)
        await refresh_panel(self.channel, self.data)
        await interaction.response.send_message("✅ Réglages mis à jour.", ephemeral=True)


class StatusModal(discord.ui.Modal, title="Statut du salon"):
    statut = discord.ui.TextInput(label="Statut (ex: En pause, Chill...)", max_length=100, required=False)

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        route = discord.http.Route(
            "PUT", "/channels/{channel_id}/voice-status", channel_id=self.channel.id
        )
        try:
            await bot.http.request(route, json={"status": self.statut.value or ""})
            await interaction.response.send_message("✅ Statut mis à jour.", ephemeral=True)
        except Exception:
            await interaction.response.send_message(
                "⚠️ Impossible de définir le statut (fonctionnalité Discord récente, "
                "vérifie que ta version de discord.py est à jour).", ephemeral=True
            )


# ============================================
#  SELECTS (liste blanche / liste noire / transfert)
# ============================================
class MemberActionSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, data: dict, target_list: str, action: str):
        super().__init__(placeholder=f"Choisir un membre à {action}...", min_values=1, max_values=1)
        self.channel = channel
        self.data = data
        self.target_list = target_list  # "whitelist" ou "blacklist"
        self.action = action            # "ajouter" ou "retirer"

    async def callback(self, interaction: discord.Interaction):
        uid = self.values[0].id
        lst = self.data[self.target_list]
        if self.action == "ajouter":
            lst.add(uid)
            self.data["blacklist" if self.target_list == "whitelist" else "whitelist"].discard(uid)
        else:
            lst.discard(uid)
        await apply_permissions(self.channel, self.data)

        # Si on vient d'ajouter quelqu'un à la liste noire et qu'il est déjà dans
        # le salon, on le déconnecte immédiatement (sinon il resterait connecté
        # jusqu'à ce qu'il quitte lui-même).
        if self.target_list == "blacklist" and self.action == "ajouter":
            member = self.channel.guild.get_member(uid)
            if member and member in self.channel.members:
                try:
                    await member.move_to(None)
                except discord.HTTPException:
                    pass

        await refresh_panel(self.channel, self.data)
        await interaction.response.send_message("✅ Mis à jour.", ephemeral=True)


class ListManageView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, data: dict, target_list: str):
        super().__init__(timeout=120)
        label = "liste blanche" if target_list == "whitelist" else "liste noire"
        self.add_item(MemberActionSelect(channel, data, target_list, "ajouter"))
        self.add_item(MemberActionSelect(channel, data, target_list, "retirer"))


class KickSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, data: dict):
        super().__init__(placeholder="Choisir la personne à faire sortir...", min_values=1, max_values=1)
        self.channel = channel
        self.data = data

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]
        if target not in self.channel.members:
            await interaction.response.send_message(
                "⚠️ Cette personne n'est pas (ou plus) dans le salon.", ephemeral=True
            )
            return
        if target.id == self.data["owner_id"]:
            await interaction.response.send_message(
                "⚠️ Tu ne peux pas t'expulser toi-même du salon.", ephemeral=True
            )
            return
        try:
            await target.move_to(None)
            await interaction.response.send_message(f"✅ {target.mention} a été déconnecté du salon.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message(
                "⚠️ Impossible de déconnecter ce membre (permissions insuffisantes ?).", ephemeral=True
            )


class KickView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, data: dict):
        super().__init__(timeout=120)
        self.add_item(KickSelect(channel, data))


class TransferSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, data: dict):
        super().__init__(placeholder="Choisir le nouveau propriétaire...", min_values=1, max_values=1)
        self.channel = channel
        self.data = data

    async def callback(self, interaction: discord.Interaction):
        new_owner = self.values[0]
        if new_owner not in self.channel.members:
            await interaction.response.send_message(
                "⚠️ Le nouveau propriétaire doit être dans le salon.", ephemeral=True
            )
            return
        self.data["owner_id"] = new_owner.id
        await apply_permissions(self.channel, self.data)
        await refresh_panel(self.channel, self.data)
        await interaction.response.send_message(f"✅ Salon transféré à {new_owner.mention}.", ephemeral=True)


class TransferView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, data: dict):
        super().__init__(timeout=120)
        self.add_item(TransferSelect(channel, data))


# ============================================
#  PANNEAU DE CONTRÔLE PRINCIPAL
# ============================================
class ControlPanelView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    async def _get(self, interaction: discord.Interaction):
        data = temp_channels.get(self.channel_id)
        channel = interaction.guild.get_channel(self.channel_id)
        if not data or not channel:
            await interaction.response.send_message("⚠️ Ce salon n'existe plus.", ephemeral=True)
            return None, None
        if interaction.user.id != data["owner_id"]:
            await interaction.response.send_message(
                "⛔ Seul le propriétaire du salon peut faire ça.", ephemeral=True
            )
            return None, None
        return channel, data

    @discord.ui.button(label="🔊 Ouvert", style=discord.ButtonStyle.primary, row=0)
    async def open_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        data["mode"] = "open"
        await apply_permissions(channel, data)
        await interaction.response.edit_message(embed=build_embed(channel, data), view=self)

    @discord.ui.button(label="🔒 Fermé", style=discord.ButtonStyle.secondary, row=0)
    async def closed_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        data["mode"] = "closed"
        await apply_permissions(channel, data)
        await interaction.response.edit_message(embed=build_embed(channel, data), view=self)

    @discord.ui.button(label="🔐 Privé", style=discord.ButtonStyle.secondary, row=0)
    async def private_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        data["mode"] = "private"
        await apply_permissions(channel, data)
        await interaction.response.edit_message(embed=build_embed(channel, data), view=self)

    @discord.ui.button(label="✅ Liste blanche", style=discord.ButtonStyle.secondary, row=1)
    async def whitelist_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        await interaction.response.send_message(
            "Gérer la liste blanche :", view=ListManageView(channel, data, "whitelist"), ephemeral=True
        )

    @discord.ui.button(label="⛔ Liste noire", style=discord.ButtonStyle.secondary, row=1)
    async def blacklist_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        await interaction.response.send_message(
            "Gérer la liste noire :", view=ListManageView(channel, data, "blacklist"), ephemeral=True
        )

    @discord.ui.button(label="🚪 Expulser", style=discord.ButtonStyle.danger, row=2)
    async def kick_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        await interaction.response.send_message(
            "Choisis la personne à faire sortir du salon :", view=KickView(channel, data), ephemeral=True
        )

    @discord.ui.button(label="➡️ Purge", style=discord.ButtonStyle.danger, row=2)
    async def purge_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        for member in list(channel.members):
            if member.id != data["owner_id"] and member.id not in data["whitelist"]:
                try:
                    await member.move_to(None)
                except discord.HTTPException:
                    pass
        await interaction.response.send_message("✅ Salon purgé.", ephemeral=True)

    @discord.ui.button(label="🎙️ Micro", style=discord.ButtonStyle.secondary, row=3)
    async def mic_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        data["mic_allowed"] = not data["mic_allowed"]
        await apply_permissions(channel, data)
        await interaction.response.edit_message(embed=build_embed(channel, data), view=self)

    @discord.ui.button(label="🎥 Vidéo", style=discord.ButtonStyle.secondary, row=3)
    async def video_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        data["video_allowed"] = not data["video_allowed"]
        await apply_permissions(channel, data)
        await interaction.response.edit_message(embed=build_embed(channel, data), view=self)

    @discord.ui.button(label="🔉 Soundboards", style=discord.ButtonStyle.secondary, row=3)
    async def soundboard_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        data["soundboard_allowed"] = not data["soundboard_allowed"]
        await apply_permissions(channel, data)
        await interaction.response.edit_message(embed=build_embed(channel, data), view=self)

    @discord.ui.button(label="📊 Statut", style=discord.ButtonStyle.secondary, row=4)
    async def status_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        await interaction.response.send_modal(StatusModal(channel))

    @discord.ui.button(label="👑 Transférer", style=discord.ButtonStyle.secondary, row=4)
    async def transfer_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        await interaction.response.send_message(
            "Choisis le nouveau propriétaire :", view=TransferView(channel, data), ephemeral=True
        )

    @discord.ui.button(label="⚙️ Réglages", style=discord.ButtonStyle.secondary, row=4)
    async def settings_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        await interaction.response.send_modal(SettingsModal(channel, data))

    @discord.ui.button(label="💾 Sauvegarder", style=discord.ButtonStyle.success, row=4)
    async def save_btn(self, interaction, button):
        channel, data = await self._get(interaction)
        if not data:
            return
        presets[str(data["owner_id"])] = {
            "mode": data["mode"],
            "mic_allowed": data["mic_allowed"],
            "video_allowed": data["video_allowed"],
            "soundboard_allowed": data["soundboard_allowed"],
        }
        save_presets()
        await interaction.response.send_message("✅ Préférences sauvegardées pour tes prochains salons.", ephemeral=True)


# ============================================
#  MODÉRATION AUTOMATIQUE (liens + injures)
# ============================================
def normalize_text(text: str) -> str:
    """Enlève les accents et met en minuscules, pour repérer les mots même déguisés (é -> e...)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def find_banned_word(content: str, banned_words: list) -> str | None:
    normalized = normalize_text(content)
    for word in banned_words:
        pattern = r"\b" + re.escape(normalize_text(word)) + r"\b"
        if re.search(pattern, normalized):
            return word
    return None


def is_exempt(member: discord.Member, cfg: dict) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
        return True
    if cfg["mod_exempt_role_id"]:
        role = member.guild.get_role(cfg["mod_exempt_role_id"])
        if role and role in member.roles:
            return True
    return False


async def timeout_member(member: discord.Member, cfg: dict, reason: str):
    try:
        duration = datetime.timedelta(minutes=cfg["mod_timeout_minutes"])
        await member.timeout(duration, reason=reason)
    except discord.Forbidden:
        pass  # le bot n'a pas la permission "Modérer les membres" ou rôle trop bas


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    cfg = get_config(message.guild.id)
    member = message.author

    if not is_exempt(member, cfg):
        # --- Filtre liens ---
        if cfg["mod_filter_links"] and LINK_REGEX.search(message.content):
            if message.channel.id not in cfg["mod_allowed_link_channel_ids"]:
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                await timeout_member(member, cfg, "Envoi d'un lien non autorisé")
                warn = await message.channel.send(
                    f"🔗 {member.mention}, les liens ne sont pas autorisés ici. "
                    f"Tu es mis en timeout {cfg['mod_timeout_minutes']} minute(s)."
                )
                await warn.delete(delay=8)
                return  # on ne cumule pas avec le filtre injures sur le même message

        # --- Filtre injures ---
        if cfg["mod_filter_insults"]:
            found = find_banned_word(message.content, cfg["mod_banned_words"])
            if found:
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                await timeout_member(member, cfg, f"Langage inapproprié détecté")
                warn = await message.channel.send(
                    f"🤬 {member.mention}, merci de rester respectueux. "
                    f"Tu es mis en timeout {cfg['mod_timeout_minutes']} minute(s)."
                )
                await warn.delete(delay=8)
                return

    # Permet aux commandes préfixées (!xxx) de continuer à fonctionner
    await bot.process_commands(message)


# ============================================
#  ÉVÉNEMENTS
# ============================================
@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")
    try:
        # Synchronisation instantanée sur chaque serveur où le bot est présent
        # (la synchronisation globale peut prendre jusqu'à 1h avant d'apparaître)
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        print(f"🔗 Commandes slash synchronisées sur {len(bot.guilds)} serveur(s).")
    except Exception as e:
        print(f"⚠️ Erreur de synchronisation des commandes : {e}")


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    cfg = get_config(guild.id)

    # Le salon déclencheur : celui configuré via /config, sinon on retombe sur le nom par défaut
    is_trigger = False
    if after.channel:
        if cfg["trigger_channel_id"]:
            is_trigger = after.channel.id == cfg["trigger_channel_id"]
        else:
            is_trigger = after.channel.name == DEFAULT_TRIGGER_CHANNEL_NAME

    if is_trigger:
        category = after.channel.category
        if cfg["category_id"]:
            found = guild.get_channel(cfg["category_id"])
            if found:
                category = found

        new_channel = await guild.create_voice_channel(
            name=f"{cfg['prefix']} Salon de {member.display_name}",
            category=category,
        )
        await member.move_to(new_channel)

        data = default_data(member.id, guild.id)
        temp_channels[new_channel.id] = data
        await apply_permissions(new_channel, data)

        panel_msg = await new_channel.send(embed=build_embed(new_channel, data), view=ControlPanelView(new_channel.id))
        data["panel_message_id"] = panel_msg.id

    # Suppression du salon quand il devient vide
    if before.channel and before.channel.id in temp_channels:
        if len(before.channel.members) == 0:
            del temp_channels[before.channel.id]
            try:
                await before.channel.delete()
            except discord.NotFound:
                pass


# ============================================
#  COMMANDES DE CONFIGURATION (/config ...)
#  Réservées aux membres avec la permission "Gérer le serveur"
# ============================================
config_group = app_commands.Group(
    name="config", description="Configurer le système de salons vocaux temporaires"
)


@config_group.command(name="voir", description="Afficher la configuration actuelle")
async def config_voir(interaction: discord.Interaction):
    cfg = get_config(interaction.guild.id)
    trigger = f"<#{cfg['trigger_channel_id']}>" if cfg["trigger_channel_id"] else f"nom = `{DEFAULT_TRIGGER_CHANNEL_NAME}` (non configuré)"
    category = f"<#{cfg['category_id']}>" if cfg["category_id"] else "même catégorie que le salon déclencheur"
    embed = discord.Embed(title="⚙️ Configuration des salons temporaires", color=discord.Color.blurple())
    embed.add_field(name="Salon déclencheur", value=trigger, inline=False)
    embed.add_field(name="Catégorie des salons créés", value=category, inline=False)
    embed.add_field(name="Préfixe du nom", value=f"`{cfg['prefix']}`", inline=True)
    embed.add_field(name="Mode par défaut", value=cfg["default_mode"], inline=True)
    visible_role = f"<@&{cfg['visible_role_id']}>" if cfg["visible_role_id"] else "Aucun (visible selon le mode pour @everyone)"
    embed.add_field(name="Rôle requis pour voir les salons", value=visible_role, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@config_group.command(name="salon_declencheur", description="Définir le salon vocal à rejoindre pour créer un salon temporaire")
@app_commands.describe(salon="Le salon vocal déclencheur")
async def config_trigger(interaction: discord.Interaction, salon: discord.VoiceChannel):
    cfg = get_config(interaction.guild.id)
    cfg["trigger_channel_id"] = salon.id
    save_configs()
    await interaction.response.send_message(f"✅ Salon déclencheur défini sur {salon.mention}.", ephemeral=True)


@config_group.command(name="categorie", description="Définir la catégorie où seront créés les salons temporaires")
@app_commands.describe(categorie="La catégorie cible")
async def config_category(interaction: discord.Interaction, categorie: discord.CategoryChannel):
    cfg = get_config(interaction.guild.id)
    cfg["category_id"] = categorie.id
    save_configs()
    await interaction.response.send_message(f"✅ Catégorie définie sur **{categorie.name}**.", ephemeral=True)


@config_group.command(name="prefixe", description="Définir le préfixe utilisé dans le nom des salons créés")
@app_commands.describe(prefixe="Ex: 🔊, 🎧, [TEMP]...")
async def config_prefix(interaction: discord.Interaction, prefixe: str):
    cfg = get_config(interaction.guild.id)
    cfg["prefix"] = prefixe
    save_configs()
    await interaction.response.send_message(f"✅ Préfixe défini sur `{prefixe}`.", ephemeral=True)


@config_group.command(name="mode_defaut", description="Définir le mode par défaut des nouveaux salons")
@app_commands.describe(mode="Mode appliqué par défaut aux nouveaux salons")
@app_commands.choices(mode=[
    app_commands.Choice(name="Ouvert", value="open"),
    app_commands.Choice(name="Fermé", value="closed"),
    app_commands.Choice(name="Privé", value="private"),
])
async def config_default_mode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    cfg = get_config(interaction.guild.id)
    cfg["default_mode"] = mode.value
    save_configs()
    await interaction.response.send_message(f"✅ Mode par défaut défini sur **{mode.name}**.", ephemeral=True)


@config_group.command(name="role_visible", description="Définir le rôle requis pour voir/rejoindre les salons temporaires (ex: Membre)")
@app_commands.describe(role="Le rôle autorisé (laisse vide pour revenir à tout le monde)")
async def config_visible_role(interaction: discord.Interaction, role: discord.Role = None):
    cfg = get_config(interaction.guild.id)
    cfg["visible_role_id"] = role.id if role else None
    save_configs()
    msg = f"✅ Seuls les membres avec le rôle {role.mention} verront les salons temporaires." if role else "✅ Les salons temporaires seront de nouveau visibles selon le mode (ouvert/fermé/privé) pour @everyone."
    await interaction.response.send_message(msg, ephemeral=True)


@config_group.command(name="reset", description="Réinitialiser la configuration de ce serveur")
async def config_reset(interaction: discord.Interaction):
    configs[str(interaction.guild.id)] = {}
    get_config(interaction.guild.id)
    save_configs()
    await interaction.response.send_message("✅ Configuration réinitialisée.", ephemeral=True)


# --- Sous-groupe /config moderation ... ---
moderation_group = app_commands.Group(
    name="moderation", description="Configurer le filtre anti-liens / anti-injures", parent=config_group
)


@moderation_group.command(name="voir", description="Afficher la config de modération actuelle")
async def mod_voir(interaction: discord.Interaction):
    cfg = get_config(interaction.guild.id)
    role = f"<@&{cfg['mod_exempt_role_id']}>" if cfg["mod_exempt_role_id"] else "Aucun (seuls les admins/modos sont exemptés)"
    embed = discord.Embed(title="🛡️ Modération automatique", color=discord.Color.red())
    embed.add_field(name="Filtre liens", value="✅ Activé" if cfg["mod_filter_links"] else "❌ Désactivé", inline=True)
    embed.add_field(name="Filtre injures", value="✅ Activé" if cfg["mod_filter_insults"] else "❌ Désactivé", inline=True)
    embed.add_field(name="Durée du timeout", value=f"{cfg['mod_timeout_minutes']} min", inline=True)
    embed.add_field(name="Rôle exempté", value=role, inline=False)
    embed.add_field(name="Mots surveillés", value=f"{len(cfg['mod_banned_words'])} mot(s) — voir `/config moderation liste_mots`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@moderation_group.command(name="liens", description="Activer/désactiver le filtre anti-liens")
@app_commands.describe(actif="Activer le filtre ?")
async def mod_links(interaction: discord.Interaction, actif: bool):
    cfg = get_config(interaction.guild.id)
    cfg["mod_filter_links"] = actif
    save_configs()
    await interaction.response.send_message(f"✅ Filtre liens {'activé' if actif else 'désactivé'}.", ephemeral=True)


@moderation_group.command(name="injures", description="Activer/désactiver le filtre anti-injures")
@app_commands.describe(actif="Activer le filtre ?")
async def mod_insults(interaction: discord.Interaction, actif: bool):
    cfg = get_config(interaction.guild.id)
    cfg["mod_filter_insults"] = actif
    save_configs()
    await interaction.response.send_message(f"✅ Filtre injures {'activé' if actif else 'désactivé'}.", ephemeral=True)


@moderation_group.command(name="duree_timeout", description="Définir la durée du timeout (en minutes)")
@app_commands.describe(minutes="Durée en minutes (1 à 40320)")
async def mod_duration(interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 40320]):
    cfg = get_config(interaction.guild.id)
    cfg["mod_timeout_minutes"] = minutes
    save_configs()
    await interaction.response.send_message(f"✅ Durée du timeout définie sur {minutes} minute(s).", ephemeral=True)


@moderation_group.command(name="ajouter_mot", description="Ajouter un mot à la liste des mots interdits")
@app_commands.describe(mot="Le mot à bloquer")
async def mod_add_word(interaction: discord.Interaction, mot: str):
    cfg = get_config(interaction.guild.id)
    mot_normalise = mot.strip().lower()
    if mot_normalise in cfg["mod_banned_words"]:
        await interaction.response.send_message("⚠️ Ce mot est déjà dans la liste.", ephemeral=True)
        return
    cfg["mod_banned_words"].append(mot_normalise)
    save_configs()
    await interaction.response.send_message(f"✅ Mot ajouté à la liste ({len(cfg['mod_banned_words'])} mot(s) au total).", ephemeral=True)


@moderation_group.command(name="retirer_mot", description="Retirer un mot de la liste des mots interdits")
@app_commands.describe(mot="Le mot à retirer")
async def mod_remove_word(interaction: discord.Interaction, mot: str):
    cfg = get_config(interaction.guild.id)
    mot_normalise = mot.strip().lower()
    if mot_normalise not in cfg["mod_banned_words"]:
        await interaction.response.send_message("⚠️ Ce mot n'est pas dans la liste.", ephemeral=True)
        return
    cfg["mod_banned_words"].remove(mot_normalise)
    save_configs()
    await interaction.response.send_message("✅ Mot retiré de la liste.", ephemeral=True)


@moderation_group.command(name="liste_mots", description="Voir la liste actuelle des mots interdits")
async def mod_list_words(interaction: discord.Interaction):
    cfg = get_config(interaction.guild.id)
    words = ", ".join(f"`{w}`" for w in cfg["mod_banned_words"]) or "Aucun"
    await interaction.response.send_message(f"**Mots surveillés :** {words}", ephemeral=True)


@moderation_group.command(name="role_exempte", description="Définir un rôle exempté du filtre (ex: Modérateur)")
@app_commands.describe(role="Le rôle à exempter (laisse vide pour retirer)")
async def mod_exempt_role(interaction: discord.Interaction, role: discord.Role = None):
    cfg = get_config(interaction.guild.id)
    cfg["mod_exempt_role_id"] = role.id if role else None
    save_configs()
    msg = f"✅ Rôle exempté défini sur {role.mention}." if role else "✅ Rôle exempté retiré."
    await interaction.response.send_message(msg, ephemeral=True)


@moderation_group.command(name="autoriser_liens_ici", description="Autoriser les liens dans le salon actuel")
@app_commands.describe(actif="True pour autoriser les liens ici, False pour les bloquer à nouveau")
async def mod_allow_links_here(interaction: discord.Interaction, actif: bool):
    cfg = get_config(interaction.guild.id)
    cid = interaction.channel.id
    if actif and cid not in cfg["mod_allowed_link_channel_ids"]:
        cfg["mod_allowed_link_channel_ids"].append(cid)
    elif not actif and cid in cfg["mod_allowed_link_channel_ids"]:
        cfg["mod_allowed_link_channel_ids"].remove(cid)
    save_configs()
    await interaction.response.send_message(
        f"✅ Liens {'autorisés' if actif else 'de nouveau bloqués'} dans ce salon.", ephemeral=True
    )


@config_group.error
async def config_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "⛔ Il faut la permission **Gérer le serveur** pour utiliser ces commandes.", ephemeral=True
        )
    else:
        await interaction.response.send_message(f"⚠️ Erreur : {error}", ephemeral=True)


# Toutes les commandes du groupe nécessitent "Gérer le serveur"
config_group.default_permissions = discord.Permissions(manage_guild=True)
bot.tree.add_command(config_group)


def resolve_token() -> str:
    """Cherche le token : 1) variable d'environnement, 2) fichier token.txt à côté de bot.py, 3) saisie manuelle (uniquement en local)."""
    if TOKEN:
        return TOKEN

    token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
    if os.path.exists(token_file):
        with open(token_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content

    # Sur un serveur (Railway, etc.) il n'y a pas de terminal interactif :
    # on ne tente input() que si stdin est disponible, sinon on échoue avec un message clair.
    if sys.stdin and sys.stdin.isatty():
        print("Aucun token trouvé (ni variable d'environnement, ni token.txt).")
        typed = input("Colle ton token Discord ici puis appuie sur Entrée : ").strip()
        if typed:
            with open(token_file, "w", encoding="utf-8") as f:
                f.write(typed)
            print(f"✅ Token enregistré dans {token_file} pour les prochains lancements.")
            return typed

    return ""


if __name__ == "__main__":
    final_token = resolve_token()
    if not final_token:
        raise RuntimeError(
            "❌ Aucun token trouvé. Sur un hébergeur (Railway, etc.) : ajoute une variable "
            "d'environnement DISCORD_TOKEN dans les Settings/Variables du projet. "
            "En local : lance le script normalement, il te le demandera."
        )
    # Diagnostic sûr : n'affiche jamais le token complet, juste sa forme, pour repérer
    # un problème de copier-coller (espaces, guillemets, token tronqué...).
    has_space = any(c.isspace() for c in final_token)
    has_quote = '"' in final_token or "'" in final_token
    is_ascii = final_token.isascii()
    print(f"🔎 Token détecté — longueur: {len(final_token)} caractères, "
          f"commence par '{final_token[:6]}', contient {final_token.count('.')} point(s) "
          f"(un vrai token Discord en contient normalement 2). "
          f"Espace(s) caché(s): {has_space} | Guillemet(s) résiduel(s): {has_quote} | "
          f"100% ASCII (pas de caractère invisible/spécial): {is_ascii}")
    bot.run(final_token)
