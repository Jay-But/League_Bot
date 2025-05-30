import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from utils.guild_logger import get_guild_logger
from utils.comprehensive_logger import get_comprehensive_logger
from utils.team_utils import team_autocomplete
from datetime import datetime
import pytz
import asyncio

# CONFIG_FILE, load_config, save_config removed
DRAFT_FILE = "config/draft.json"

def load_guild_config(guild_id):
    config_file = f"config/setup_{str(guild_id)}.json"
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {} # Return empty if file is corrupted
    return {}

def save_guild_config(guild_id, config_data):
    os.makedirs("config", exist_ok=True) # Ensure 'config' directory exists
    config_file = f"config/setup_{str(guild_id)}.json"
    with open(config_file, 'w') as f:
        json.dump(config_data, f, indent=4)

def load_draft():
    if os.path.exists(DRAFT_FILE):
        with open(DRAFT_FILE, 'r') as f:
            return json.load(f)
    return {"draft_active": False}

class ConfirmModal(discord.ui.Modal):
    def __init__(self, action, callback):
        super().__init__(title=f"Confirm {action}")
        self.callback = callback
        self.add_item(discord.ui.TextInput(
            label="Type 'confirm' to proceed",
            required=True
        ))

    async def on_submit(self, interaction: discord.Interaction):
        if self.children[0].value.lower() != "confirm":
            await interaction.response.send_message("Confirmation failed. Action cancelled.", ephemeral=True)
            return
        await self.callback(interaction)

class TransactionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.config and self.team_emojis removed

    async def log_action(self, guild, action, details):
        guild_config = load_guild_config(guild.id)
        logs_channel_id = guild_config.get("logs_channel") # Assuming top-level key
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Transaction: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                await logs_channel.send(embed=embed)

    def get_team_info(self, member: discord.Member):
        guild_config = load_guild_config(member.guild.id)
        teams = guild_config.get("teams", [])
        team_emojis = guild_config.get("team_emojis", {})
        for role in member.roles:
            if role.name in teams and role.name != "@everyone":
                emoji = team_emojis.get(role.name, "")
                return role, role.name, emoji
        return None, None, None

    def get_team_members(self, guild: discord.Guild, team_name: str):
        team_role = discord.utils.get(guild.roles, name=team_name)
        if not team_role:
            return []
        return [member for member in guild.members if team_role in member.roles]

    def check_trade_deadline(self, guild_id: int): # Added guild_id parameter
        guild_config = load_guild_config(guild_id)
        deadline_str = guild_config.get("trade_deadline") # Assuming top-level key
        if not deadline_str:
            return True # No deadline set, trades always allowed
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
            return datetime.now(pytz.UTC) <= deadline
        except ValueError:
            return True # Invalid format, default to allowing

    def get_franchise_role(self, member: discord.Member):
        # This method does not use self.config, so it's fine as is.
        # However, franchise_roles could be made configurable per guild in the future.
        franchise_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
        for role in member.roles:
            if role.name in franchise_roles:
                return role.name
        return None

    def get_guild_config(self, guild_id: int):
        return load_guild_config(guild_id) # Use the standalone helper

    def has_required_roles(self, interaction: discord.Interaction):
        """Check if the user has the roles configured in setup."""
        guild_config = self.get_guild_config(interaction.guild.id)
        required_roles = guild_config.get("roles", {}).get("manage_teams", [])
        if not required_roles:
            return False
        user_roles = [role.id for role in interaction.user.roles]
        return any(int(role_id) in user_roles for role_id in required_roles)

    def get_transactions_channel(self, guild: discord.Guild):
        """Get the transactions channel configured in setup."""
        guild_config = self.get_guild_config(guild.id)
        transactions_channel_id = guild_config.get("channels", {}).get("transactions")
        if transactions_channel_id:
            return guild.get_channel(int(transactions_channel_id))
        return None

    # CPU Break: Pause after cog initialization
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="sign", description="Sign a player to your team.")
    @app_commands.describe(player="The player to sign")
    async def sign(self, interaction: discord.Interaction, player: discord.Member):
        # Check if user has required roles from setup
        if not self.has_required_roles(interaction):
            await interaction.response.send_message("❌ You don't have permission to sign players. Please contact an administrator to configure roles via `/setup`.", ephemeral=True)
            return

        # Get the user's team role
        team_role, team_name, team_emoji = self.get_team_info(interaction.user)
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return

        player_team_role, player_team, _ = self.get_team_info(player)
        if player_team:
            await interaction.response.send_message(f"{player.display_name} is already on {player_team}.", ephemeral=True)
            return

        guild_config_sign = load_guild_config(interaction.guild.id) # Load for this command scope
        roster_cap = int(guild_config_sign.get("roster_cap", 53))
        current_roster = len(self.get_team_members(interaction.guild, team_name))
        if current_roster >= roster_cap:
            await interaction.response.send_message(f"{team_name} has reached the roster cap ({roster_cap}).", ephemeral=True)
            return

        try:
            await player.add_roles(team_role)
            coach_role = self.get_franchise_role(interaction.user)
            embed = discord.Embed(
                title="Signing Complete",
                description=f"{player.mention} has been signed by {team_emoji} {team_name}",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            if interaction.guild.icon:
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
            embed.add_field(name="Coach:", value=f"{coach_role} {interaction.user.mention}", inline=False)
            embed.add_field(name="Roster:", value=f"{current_roster + 1}/{roster_cap}", inline=False)

            team_emojis_sign = guild_config_sign.get("team_emojis", {}) # Load from guild_config
            team_emoji_url_check = team_emojis_sign.get(team_name, "") # Renamed
            if team_emoji_url_check:
                try:
                    # Extract emoji URL if it's a custom emoji
                    if team_emoji_url_check.startswith('<:') and team_emoji_url_check.endswith('>'):
                        # Custom emoji format: <:name:id>
                        emoji_id = team_emoji_url_check.split(':')[-1].rstrip('>')
                        emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png"
                        embed.set_thumbnail(url=emoji_url)
                    elif team_emoji_url_check.startswith('<a:') and team_emoji_url_check.endswith('>'):
                        # Animated emoji format: <a:name:id>
                        emoji_id = team_emoji_url_check.split(':')[-1].rstrip('>')
                        emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.gif"
                        embed.set_thumbnail(url=emoji_url)
                except Exception:
                    pass  # If emoji URL fails, just skip the thumbnail

            # Send to transactions channel from guild-specific setup
            # guild_config_sign is already loaded
            transactions_channel_id = guild_config_sign.get("channels", {}).get("transactions")
            if transactions_channel_id:
                transactions_channel = interaction.guild.get_channel(int(transactions_channel_id))
                if transactions_channel:
                    await transactions_channel.send(embed=embed)
                # If channel not found, maybe send to interaction.channel as fallback or log an error?
                # For now, matching original behavior of only sending if found.
            else:
                # If no transactions_channel_id, consider sending a message to the user or current channel.
                # Original code sent a warning to interaction.response if channel not configured.
                # This part of the logic is tricky because response might have been sent already.
                # For now, if channel isn't configured, the message just doesn't go to that specific channel.
                # The ephemeral "Player signed successfully!" will still be sent.
                pass # No specific message if channel not configured, to avoid double response.

            await interaction.response.send_message("Player signed successfully!", ephemeral=True)
            await self.log_action(interaction.guild, "Player Signed", f"{player.display_name} to {team_name}")
        except discord.errors.HTTPException as e:
            # Check if response has been sent before trying to send another one.
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Failed to sign player: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"Failed to sign player: {e}", ephemeral=True)

    # CPU Break: Pause after /sign
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="offer", description="Make an offer to a player.")
    @app_commands.describe(player="The player to offer a contract to")
    async def offer(self, interaction: discord.Interaction, player: discord.Member):
        # Check if user has required roles from setup
        if not self.has_required_roles(interaction):
            await interaction.response.send_message("❌ You don't have permission to make offers. Please contact an administrator to configure roles via `/setup`.", ephemeral=True)
            return

        guild_config_offer = load_guild_config(interaction.guild.id) # Load guild_config

        draft_data = load_draft()
        if draft_data.get("draft_active", False):
            await interaction.response.send_message("Offers are disabled during an active draft.", ephemeral=True)
            return

        if not self.check_trade_deadline(interaction.guild.id): # Pass guild_id
            await interaction.response.send_message("The trade deadline has passed.", ephemeral=True)
            return

        team_role, team_name, team_emoji = self.get_team_info(interaction.user) # Uses load_guild_config internally
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return

        player_team_role, player_team, _ = self.get_team_info(player) # Uses load_guild_config internally
        if player_team:
            await interaction.response.send_message(f"{player.display_name} is already on {player_team}.", ephemeral=True)
            return

        roster_cap_offer = int(guild_config_offer.get("roster_cap", 53)) # Use guild_config
        current_roster = len(self.get_team_members(interaction.guild, team_name))
        if current_roster >= roster_cap_offer:
            await interaction.response.send_message(f"{team_name} has reached the roster cap ({roster_cap_offer}).", ephemeral=True)
            return

        class OfferView(discord.ui.View):
            def __init__(self, bot, player_view, team_role_view, team_name_view, team_emoji_view, coach_role_view, guild_config_view, roster_cap_view): # Pass guild_config and roster_cap
                super().__init__(timeout=86400)  # 24 hours
                self.bot = bot
                self.player = player_view
                self.team_role = team_role_view
                self.team_name = team_name_view
                self.team_emoji = team_emoji_view
                self.coach_role = coach_role_view
                self.guild_config = guild_config_view # Store guild_config
                self.roster_cap = roster_cap_view # Store roster_cap

            async def on_timeout(self):
                self.stop()

            @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
            async def accept_button(self, interaction_view: discord.Interaction, button: discord.ui.Button): # Renamed
                if interaction_view.user != self.player:
                    await interaction_view.response.send_message("Only the offered player can accept.", ephemeral=True)
                    return
                try:
                    await self.player.add_roles(self.team_role)
                    current_roster_accept = len(self.bot.get_cog("TransactionsCog").get_team_members(interaction_view.guild, self.team_name))
                    embed_accept = discord.Embed( # Renamed
                        title="Offer Accepted",
                        description=f"{self.player.mention} has accepted the offer to join {self.team_emoji} {self.team_name}",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    if interaction_view.guild.icon:
                        embed_accept.set_author(name=interaction_view.guild.name, icon_url=interaction_view.guild.icon.url)
                    embed_accept.add_field(name="Coach:", value=f"{self.coach_role} {interaction_view.user.mention}", inline=False) # Used interaction_view
                    embed_accept.add_field(name="Roster:", value=f"{current_roster_accept}/{self.roster_cap}", inline=False) # Use stored roster_cap

                    # Team emoji for thumbnail - check if it's an actual URL or just the string representation
                    # Assuming team_emoji is the string representation from config, try to parse if custom emoji
                    team_emoji_str_accept = self.guild_config.get("team_emojis", {}).get(self.team_name, "")
                    if team_emoji_str_accept.startswith('<:') and team_emoji_str_accept.endswith('>'):
                        emoji_id_accept = team_emoji_str_accept.split(':')[-1].rstrip('>')
                        embed_accept.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_accept}.png")
                    elif team_emoji_str_accept.startswith('<a:') and team_emoji_str_accept.endswith('>'):
                        emoji_id_accept = team_emoji_str_accept.split(':')[-1].rstrip('>')
                        embed_accept.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_accept}.gif")

                    transactions_channel_id = self.guild_config.get("channels", {}).get("transactions") # Use stored guild_config
                    if transactions_channel_id:
                        transactions_channel = interaction_view.guild.get_channel(int(transactions_channel_id))
                        if transactions_channel:
                            await transactions_channel.send(embed=embed_accept)
                    await interaction_view.response.send_message("Contract accepted!", ephemeral=True)
                    await self.bot.get_cog("TransactionsCog").log_action(
                        interaction_view.guild,
                        "Contract Accepted",
                        f"{self.player.display_name} joined {self.team_name}"
                    )
                    self.stop()
                except discord.errors.HTTPException as e:
                    await interaction_view.response.send_message(f"Failed to accept contract: {e}", ephemeral=True)

            @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
            async def decline_button(self, interaction_view: discord.Interaction, button: discord.ui.Button): # Renamed
                if interaction_view.user != self.player:
                    await interaction_view.response.send_message("Only the offered player can decline.", ephemeral=True)
                    return
                await interaction_view.response.send_message("Contract declined.", ephemeral=True)
                await self.bot.get_cog("TransactionsCog").log_action(
                    interaction_view.guild,
                    "Contract Declined",
                    f"{self.player.display_name} declined {self.team_name}"
                )
                self.stop()

        view = OfferView(self.bot, player, team_role, team_name, team_emoji, self.get_franchise_role(interaction.user), guild_config_offer, roster_cap_offer)
        embed_offer = discord.Embed( # Renamed
            title="Contract Offer",
            description=f"{player.mention}, you have received a contract offer from {team_emoji} {team_name}.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        await player.send(embed=embed, view=view)
        await interaction.response.send_message("Contract offer sent to player's DMs!", ephemeral=True)
        await self.log_action(interaction.guild, "Contract Offered", f"To {player.display_name} from {team_name}")

    # CPU Break: Pause after /offer
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="demand", description="Demand a player be removed from your team.")
    @app_commands.checks.has_any_role("General Manager", "Head Coach", "Assistant Coach")
    @app_commands.describe(player="The player to demand removal from")
    async def demand(self, interaction: discord.Interaction, player: discord.Member):
        team_role, team_name, team_emoji = self.get_team_info(interaction.user)
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return

        if "Franchise Owner" in [role.name for role in interaction.user.roles]:
            await interaction.response.send_message("Franchise Owners cannot use this command.", ephemeral=True)
            return

        if team_role not in player.roles:
            await interaction.response.send_message(f"{player.display_name} is not on your team.", ephemeral=True)
            return

        try:
            await player.remove_roles(team_role)
            franchise_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
            roles_to_remove = [r for r in player.roles if r.name in franchise_roles]
            if roles_to_remove:
                await player.remove_roles(*roles_to_remove)
            current_roster = len(self.get_team_members(interaction.guild, team_name))
            embed = discord.Embed(
                title="Demand Successful",
                description=f"{player.mention} has demanded from {team_emoji} {team_name}",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            guild_config_demand = load_guild_config(interaction.guild.id) # Load guild_config
            if interaction.guild.icon:
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
            embed.add_field(name="Roster:", value=f"{current_roster - 1}/{int(guild_config_demand.get('roster_cap', 53))}", inline=False)

            # Assuming team_emoji is the string representation from get_team_info (which uses guild_config)
            # Attempt to use it for thumbnail if it's a custom emoji URL/string
            team_emojis_demand = guild_config_demand.get("team_emojis", {})
            actual_team_emoji_str = team_emojis_demand.get(team_name, "") # team_name from get_team_info
            if actual_team_emoji_str.startswith('<:') and actual_team_emoji_str.endswith('>'):
                emoji_id_demand = actual_team_emoji_str.split(':')[-1].rstrip('>')
                embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_demand}.png")
            elif actual_team_emoji_str.startswith('<a:') and actual_team_emoji_str.endswith('>'):
                emoji_id_demand = actual_team_emoji_str.split(':')[-1].rstrip('>')
                embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_demand}.gif")

            demands_channel_id = guild_config_demand.get("channels", {}).get("demands") # Get from guild_config
            demands_channel = interaction.guild.get_channel(int(demands_channel_id)) if demands_channel_id else interaction.channel
            await demands_channel.send(embed=embed)
            await interaction.response.send_message("Demand processed successfully!", ephemeral=True)
            await self.log_action(interaction.guild, "Demand Successful", f"{player.display_name} from {team_name}")
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to process demand: {e}", ephemeral=True)

    # CPU Break: Pause after /demand
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="promote", description="Promote a player to a franchise role.")
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager", "Head Coach")
    @app_commands.describe(player="The player to promote", role="The franchise role to assign")
    @app_commands.choices(role=[
        app_commands.Choice(name="General Manager", value="General Manager"),
        app_commands.Choice(name="Head Coach", value="Head Coach"),
        app_commands.Choice(name="Assistant Coach", value="Assistant Coach")
    ])
    async def promote(self, interaction: discord.Interaction, player: discord.Member, role: str):
        team_role, team_name, team_emoji = self.get_team_info(interaction.user)
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return
        if team_role not in player.roles:
            await interaction.response.send_message(f"{player.display_name} is not on your team.", ephemeral=True)
            return

        user_role = self.get_franchise_role(interaction.user)
        role_hierarchy = {"Franchise Owner": 3, "General Manager": 2, "Head Coach": 1, "Assistant Coach": 0}
        if role_hierarchy.get(user_role, -1) <= role_hierarchy.get(role, -1):
            await interaction.response.send_message("You cannot promote to a role equal to or higher than your own.", ephemeral=True)
            return

        target_role = discord.utils.get(interaction.guild.roles, name=role)
        if not target_role:
            await interaction.response.send_message(f"Role {role} not found.", ephemeral=True)
            return

        try:
            await player.add_roles(target_role)
            coach_role = self.get_franchise_role(interaction.user)
            embed = discord.Embed(
                title="Promotion Complete",
                description=f"{team_emoji} {team_name} have promoted {player.mention} to {role}",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            guild_config_promote = load_guild_config(interaction.guild.id) # Load guild_config
            if interaction.guild.icon:
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
            embed.add_field(name="Coach:", value=f"{coach_role} {interaction.user.mention}", inline=False)

            team_emojis_promote = guild_config_promote.get("team_emojis", {})
            actual_team_emoji_str_promote = team_emojis_promote.get(team_name, "")
            if actual_team_emoji_str_promote.startswith('<:') and actual_team_emoji_str_promote.endswith('>'):
                emoji_id_promote = actual_team_emoji_str_promote.split(':')[-1].rstrip('>')
                embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_promote}.png")
            elif actual_team_emoji_str_promote.startswith('<a:') and actual_team_emoji_str_promote.endswith('>'):
                emoji_id_promote = actual_team_emoji_str_promote.split(':')[-1].rstrip('>')
                embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_promote}.gif")

            transactions_channel_id = guild_config_promote.get("channels", {}).get("transactions") # Get from guild_config
            transactions_channel = interaction.guild.get_channel(int(transactions_channel_id)) if transactions_channel_id else interaction.channel
            await transactions_channel.send(embed=embed)
            await interaction.response.send_message("Player promoted successfully!", ephemeral=True)
            await self.log_action(interaction.guild, "Player Promoted", f"{player.display_name} to {role} in {team_name}")
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to promote player: {e}", ephemeral=True)

    # CPU Break: Pause after /promote
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="demote", description="Demote a player from a franchise role.")
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager", "Head Coach")
    @app_commands.describe(player="The player to demote")
    async def demote(self, interaction: discord.Interaction, player: discord.Member):
        team_role, team_name, team_emoji = self.get_team_info(interaction.user)
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return
        if team_role not in player.roles:
            await interaction.response.send_message(f"{player.display_name} is not on your team.", ephemeral=True)
            return

        user_role = self.get_franchise_role(interaction.user)
        player_role = self.get_franchise_role(player)
        role_hierarchy = {"Franchise Owner": 3, "General Manager": 2, "Head Coach": 1, "Assistant Coach": 0}
        if not player_role or role_hierarchy.get(user_role, -1) <= role_hierarchy.get(player_role, -1):
            await interaction.response.send_message("You cannot demote someone with a role equal to or higher than your own.", ephemeral=True)
            return

        target_role = discord.utils.get(interaction.guild.roles, name=player_role)
        if not target_role:
            await interaction.response.send_message(f"Role {player_role} not found.", ephemeral=True)
            return

        try:
            await player.remove_roles(target_role)
            coach_role = self.get_franchise_role(interaction.user)
            embed = discord.Embed(
                title="Demotion Complete",
                description=f"{team_emoji} {team_name} have demoted {player.mention} from {player_role}",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            guild_config_demote = load_guild_config(interaction.guild.id) # Load guild_config
            if interaction.guild.icon:
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
            embed.add_field(name="Coach:", value=f"{coach_role} {interaction.user.mention}", inline=False)

            team_emojis_demote = guild_config_demote.get("team_emojis", {})
            actual_team_emoji_str_demote = team_emojis_demote.get(team_name, "")
            if actual_team_emoji_str_demote.startswith('<:') and actual_team_emoji_str_demote.endswith('>'):
                emoji_id_demote = actual_team_emoji_str_demote.split(':')[-1].rstrip('>')
                embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_demote}.png")
            elif actual_team_emoji_str_demote.startswith('<a:') and actual_team_emoji_str_demote.endswith('>'):
                emoji_id_demote = actual_team_emoji_str_demote.split(':')[-1].rstrip('>')
                embed.set_thumbnail(url=f"https://cdn.discordapp.com/emojis/{emoji_id_demote}.gif")

            transactions_channel_id = guild_config_demote.get("channels", {}).get("transactions") # Get from guild_config
            transactions_channel = interaction.guild.get_channel(int(transactions_channel_id)) if transactions_channel_id else interaction.channel
            await transactions_channel.send(embed=embed)
            await interaction.response.send_message("Player demoted successfully!", ephemeral=True)
            await self.log_action(interaction.guild, "Player Demoted", f"{player.display_name} from {player_role} in {team_name}")
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to demote player: {e}", ephemeral=True)

    # CPU Break: Pause after /demote
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="trade", description="Propose a trade between two teams.")
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager", "Head Coach", "Assistant Coach")
    @app_commands.describe(offered_player="The player you are offering", targeted_team="The team to trade with", targeted_player="The player you want")
    @app_commands.autocomplete(targeted_team=team_autocomplete)
    async def trade(self, interaction: discord.Interaction, offered_player: discord.Member, targeted_team: str, targeted_player: discord.Member):
        draft_data = load_draft()
        if draft_data.get("draft_active", False):
            await interaction.response.send_message("Trades are disabled during an active draft.", ephemeral=True)
            return

        guild_config_trade = load_guild_config(interaction.guild.id) # Load guild_config

        if not self.check_trade_deadline(interaction.guild.id): # Pass guild_id
            await interaction.response.send_message("The trade deadline has passed.", ephemeral=True)
            return

        team_role, user_team, team_emoji_user = self.get_team_info(interaction.user) # Renamed team_emoji
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return
        if user_team == targeted_team:
            await interaction.response.send_message("You cannot trade with your own team.", ephemeral=True)
            return

        if team_role not in offered_player.roles:
            await interaction.response.send_message(f"{offered_player.display_name} is not on your team.", ephemeral=True)
            return
        targeted_team_role = discord.utils.get(interaction.guild.roles, name=targeted_team)
        if not targeted_team_role or targeted_team_role not in targeted_player.roles:
            await interaction.response.send_message(f"{targeted_player.display_name} is not on {targeted_team}.", ephemeral=True)
            return

        roster_cap_trade = int(guild_config_trade.get("roster_cap", 53)) # Use guild_config
        user_roster = len(self.get_team_members(interaction.guild, user_team))
        targeted_roster = len(self.get_team_members(interaction.guild, targeted_team))
        if user_roster >= roster_cap_trade or targeted_roster >= roster_cap_trade: # Use var
            await interaction.response.send_message("One or both teams are at roster cap.", ephemeral=True)
            return

        team_emojis_trade = guild_config_trade.get("team_emojis", {}) # Use guild_config
        target_team_emoji = team_emojis_trade.get(targeted_team, "")
        embed_trade = discord.Embed( # Renamed
            title="Trade Proposal",
            description=f"Trade proposed by {team_emoji_user} {user_team}:", # Use renamed var
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed_trade.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        embed_trade.add_field(name=f"{team_emoji_user} {user_team} Offers", value=offered_player.mention, inline=False) # Use renamed var
        embed_trade.add_field(name=f"{target_team_emoji} {targeted_team} Offers", value=targeted_player.mention, inline=False)

        class TradeView(discord.ui.View):
            def __init__(self, bot, user_team_view, targeted_team_view, offered_player_view, targeted_player_view, team_emoji_user_view, target_team_emoji_view, guild_config_view_trade): # Pass guild_config
                super().__init__(timeout=86400)  # 24 hours
                self.bot = bot
                self.user_team = user_team_view
                self.targeted_team = targeted_team_view
                self.offered_player = offered_player_view
                self.targeted_player = targeted_player_view
                self.team_emoji_user = team_emoji_user_view # Stored
                self.target_team_emoji = target_team_emoji_view # Stored
                # FO role name should ideally come from guild_config if configurable
                self.user_fo_role = discord.utils.get(interaction.guild.roles, name="Franchise Owner")
                self.target_fo_member = None # Stored target FO member
                self.guild_config = guild_config_view_trade # Store guild_config
                self.user_team_approved = False # Initialize approval flags
                self.target_team_approved = False # Initialize approval flags


            async def start(self, initial_interaction: discord.Interaction): # Pass initial interaction
                target_team_role_obj = discord.utils.get(initial_interaction.guild.roles, name=self.targeted_team)
                self.target_fo_member = None
                # Ensure user_fo_role exists before trying to iterate
                if self.user_fo_role and target_team_role_obj:
                    for member in initial_interaction.guild.members:
                        if self.user_fo_role in member.roles and target_team_role_obj in member.roles:
                            self.target_fo_member = member
                            break
                if not self.target_fo_member:
                    # Use followup if initial response was deferred
                    if initial_interaction.response.is_done():
                         await initial_interaction.followup.send("No Franchise Owner found for the targeted team.", ephemeral=True)
                    else:
                        await initial_interaction.response.send_message("No Franchise Owner found for the targeted team.", ephemeral=True)
                    self.stop()
                    return

                # Ensure original response is sent before creating thread with it
                if not initial_interaction.response.is_done():
                    await initial_interaction.response.send_message("Trade proposal being prepared...", ephemeral=True) # Send placeholder

                thread_message = await initial_interaction.original_response()
                thread = await initial_interaction.channel.create_thread(
                    name=f"Trade: {self.user_team} vs {self.targeted_team}",
                    message=thread_message, # Use fetched message
                    auto_archive_duration=60 # Consider making this configurable
                )
                await thread.send(content=f"{initial_interaction.user.mention} {self.target_fo_member.mention}", embed=embed_trade) # Use embed_trade

            @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
            async def approve_button(self, interaction_view: discord.Interaction, button: discord.ui.Button): # Renamed
                # Check if the interactor is the original proposer or the target FO member
                if interaction_view.user != interaction.user and interaction_view.user != self.target_fo_member:
                    await interaction_view.response.send_message("Only the proposing or target Franchise Owner can approve.", ephemeral=True)
                    return

                if interaction_view.user == interaction.user and self.user_team_approved: # Proposer
                    await interaction_view.response.send_message("You have already approved this trade.", ephemeral=True)
                    return
                if interaction_view.user == self.target_fo_member and self.target_team_approved: # Target FO
                    await interaction_view.response.send_message("You have already approved this trade.", ephemeral=True)
                    return

                if interaction_view.user == interaction.user: # Proposer
                    self.user_team_approved = True
                elif interaction_view.user == self.target_fo_member: # Target FO
                    self.target_team_approved = True

                if self.user_team_approved and self.target_team_approved:
                    user_team_role_obj = discord.utils.get(interaction_view.guild.roles, name=self.user_team)
                    targeted_team_role_obj = discord.utils.get(interaction_view.guild.roles, name=self.targeted_team)
                    try:
                        await self.offered_player.remove_roles(user_team_role_obj)
                        await self.offered_player.add_roles(targeted_team_role_obj)
                        await self.targeted_player.remove_roles(targeted_team_role_obj)
                        await self.targeted_player.add_roles(user_team_role_obj)

                        embed_trade.title = "Trade Accepted" # Use embed_trade
                        embed_trade.color = discord.Color.green()
                        embed_trade.description = f"{self.target_team_emoji} {self.targeted_team} has accepted a trade from {self.team_emoji_user} {self.user_team}"
                        embed_trade.clear_fields() # Clear old offer fields
                        embed_trade.add_field(name=f"{self.team_emoji_user} {self.user_team} Receives", value=self.targeted_player.mention, inline=False)
                        embed_trade.add_field(name=f"{self.target_team_emoji} {self.targeted_team} Receives", value=self.offered_player.mention, inline=False)
                        await interaction_view.message.edit(embed=embed_trade, view=None)

                        transactions_channel_id = self.guild_config.get("channels", {}).get("transactions") # Use stored guild_config
                        transactions_channel = interaction_view.guild.get_channel(int(transactions_channel_id)) if transactions_channel_id else interaction_view.channel
                        await transactions_channel.send(embed=embed_trade)
                        # await interaction_view.response.send_message("Trade completed!", ephemeral=True) # Cannot respond here, message already edited.
                        await interaction_view.followup.send("Trade completed!", ephemeral=True)


                        await self.bot.get_cog("TransactionsCog").log_action(
                            interaction_view.guild,
                            "Trade Completed",
                            f"{self.offered_player.display_name} to {self.targeted_team}, {self.targeted_player.display_name} to {self.user_team}"
                        )
                    except discord.errors.HTTPException as e:
                        await interaction_view.response.send_message(f"Failed to execute trade: {e}", ephemeral=True)
                else:
                    await interaction_view.response.send_message("Trade approved. Waiting for other team.", ephemeral=True)

            @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
            async def reject_button(self, interaction_view: discord.Interaction, button: discord.ui.Button): # Renamed
                if interaction_view.user != interaction.user and interaction_view.user != self.target_fo_member: # Check original proposer or target FO
                    await interaction_view.response.send_message("Only the proposing or target Franchise Owner can reject.", ephemeral=True)
                    return
                embed_trade.title = "Trade Rejected" # Use embed_trade
                embed_trade.description += f"\nRejected by {interaction_view.user.mention}"
                embed_trade.color = discord.Color.red()
                await interaction_view.message.edit(embed=embed_trade, view=None)
                await interaction_view.response.send_message("Trade rejected.", ephemeral=True)
                await self.bot.get_cog("TransactionsCog").log_action(
                    interaction_view.guild,
                    "Trade Rejected",
                    f"Rejected by {interaction_view.user.display_name}"
                )
                self.stop()

        view = TradeView(self.bot, user_team, targeted_team, offered_player, targeted_player, team_emoji_user, target_team_emoji, guild_config_trade)
        await view.start(interaction) # Pass initial interaction to start
        # Message is sent by view.start or its called methods if no FO found.
        # If FO is found, original response is fetched for thread creation.
        # await interaction.response.send_message("Trade proposal started in a thread!", ephemeral=True) # This might be redundant or cause error
        await self.log_action(
            interaction.guild,
            "Trade Proposed",
            f"{offered_player.display_name} to {targeted_team}, {targeted_player.display_name} to {user_team}"
        )

    # CPU Break: Pause after /trade
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="release", description="Release a player from your team.")
    @app_commands.describe(player="The player to release")
    async def release(self, interaction: discord.Interaction, player: discord.Member):
        # Check if user has required roles from setup
        if not self.has_required_roles(interaction):
            await interaction.response.send_message("❌ You don't have permission to release players. Please contact an administrator to configure roles via `/setup`.", ephemeral=True)
            return

        team_role, team_name, team_emoji = self.get_team_info(interaction.user)
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return
        if team_role not in player.roles:
            await interaction.response.send_message(f"{player.display_name} is not on your team.", ephemeral=True)
            return

        async def release_callback(interaction: discord.Interaction):
            try:
                await player.remove_roles(team_role)
                franchise_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
                staff_to_remove = [r for r in player.roles if r.name in franchise_roles]
                if staff_to_remove:
                    await player.remove_roles(*staff_to_remove)
                current_roster = len(self.get_team_members(interaction.guild, team_name))
                coach_role = self.get_franchise_role(interaction.user)
                embed = discord.Embed(
                    title="Release Successful",
                    description=f"{team_emoji} {team_name} has officially released {player.mention}",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                if interaction.guild.icon:
                    embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
                embed.add_field(name="Coach:", value=f"{coach_role} {interaction.user.mention}", inline=False)
                embed.add_field(name="Roster:", value=f"{current_roster - 1}/{int(self.config.get('roster_cap', 53))}", inline=False)
                if team_emoji:
                    embed.set_thumbnail(url=team_emoji)  # Full-size team emoji
                # Send to transactions channel from guild-specific setup
                guild_config = self.get_guild_config(interaction.guild.id)
                transactions_channel_id = guild_config.get("channels", {}).get("transactions")
                if transactions_channel_id:
                    transactions_channel = interaction.guild.get_channel(int(transactions_channel_id))
                    if transactions_channel:
                        await transactions_channel.send(embed=embed)
                await interaction.response.send_message("Player released!", ephemeral=True)
                await self.log_action(interaction.guild, "Player Released", f"{player.display_name} from {team_name}")
            except discord.errors.HTTPException as e:
                await interaction.response.send_message(f"Failed to release player: {e}", ephemeral=True)

        modal = ConfirmModal("Release Player", release_callback)
        await interaction.response.send_modal(modal)

    # CPU Break: Pause after /release
    # asyncio.sleep(2) simulated during code generation

async def setup(bot):
    await bot.add_cog(TransactionsCog(bot))