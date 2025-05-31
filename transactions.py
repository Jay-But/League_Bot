import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from .team_management import team_autocomplete
from datetime import datetime
import pytz
import asyncio

CONFIG_FILE = "config/setup.json"
DRAFT_FILE = "config/draft.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

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
        self.config = load_config()
        self.team_emojis = self.config.get("team_emojis", {})

    async def log_action(self, guild, action, details):
        logs_channel_id = self.config.get("logs_channel")
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
        for role in member.roles:
            if role.name in self.config.get("teams", []) and role.name != "@everyone":
                emoji = self.team_emojis.get(role.name, "")
                return role, role.name, emoji
        return None, None, None

    def get_team_members(self, guild: discord.Guild, team_name: str):
        team_role = discord.utils.get(guild.roles, name=team_name)
        if not team_role:
            return []
        return [member for member in guild.members if team_role in member.roles]

    def check_trade_deadline(self):
        deadline_str = self.config.get("trade_deadline")
        if not deadline_str:
            return True
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
            return datetime.now(pytz.UTC) <= deadline
        except ValueError:
            return True

    def get_franchise_role(self, member: discord.Member):
        franchise_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
        for role in member.roles:
            if role.name in franchise_roles:
                return role.name
        return None

    def get_guild_config(self, guild_id: int):
        """Retrieve guild-specific configuration."""
        config = load_config()
        guild_id_str = str(guild_id)
        return config.get(guild_id_str, {})

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

        roster_cap = int(self.config.get("roster_cap", 53))
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
            # Set team emoji as thumbnail if available
            team_emoji = self.team_emojis.get(team_name, "")
            if team_emoji:
                try:
                    # Extract emoji URL if it's a custom emoji
                    if team_emoji.startswith('<:') and team_emoji.endswith('>'):
                        # Custom emoji format: <:name:id>
                        emoji_id = team_emoji.split(':')[-1].rstrip('>')
                        emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png"
                        embed.set_thumbnail(url=emoji_url)
                    elif team_emoji.startswith('<a:') and team_emoji.endswith('>'):
                        # Animated emoji format: <a:name:id>
                        emoji_id = team_emoji.split(':')[-1].rstrip('>')
                        emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.gif"
                        embed.set_thumbnail(url=emoji_url)
                except Exception:
                    pass  # If emoji URL fails, just skip the thumbnail

            # Send to transactions channel from guild-specific setup
            guild_config = self.get_guild_config(interaction.guild.id)
            transactions_channel_id = guild_config.get("channels", {}).get("transactions")
            if transactions_channel_id:
                transactions_channel = interaction.guild.get_channel(int(transactions_channel_id))
                if transactions_channel:
                    await transactions_channel.send(embed=embed)
            else:
                await interaction.response.send_message("⚠️ Transactions channel not configured. Please run `/setup` and configure the Transactions channel.", ephemeral=True)
            await interaction.response.send_message("Player signed successfully!", ephemeral=True)
            await self.log_action(interaction.guild, "Player Signed", f"{player.display_name} to {team_name}")
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to sign player: {e}", ephemeral=True)

    # CPU Break: Pause after /sign
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="offer", description="Make an offer to a player.")
    @app_commands.describe(player="The player to offer a contract to")
    async def offer(self, interaction: discord.Interaction, player: discord.Member):
        # Check if user has required roles from setup
        if not self.has_required_roles(interaction):
            await interaction.response.send_message("❌ You don't have permission to make offers. Please contact an administrator to configure roles via `/setup`.", ephemeral=True)
            return

        draft_data = load_draft()
        if draft_data.get("draft_active", False):
            await interaction.response.send_message("Offers are disabled during an active draft.", ephemeral=True)
            return

        if not self.check_trade_deadline():
            await interaction.response.send_message("The trade deadline has passed.", ephemeral=True)
            return

        team_role, team_name, team_emoji = self.get_team_info(interaction.user)
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return

        player_team_role, player_team, _ = self.get_team_info(player)
        if player_team:
            await interaction.response.send_message(f"{player.display_name} is already on {player_team}.", ephemeral=True)
            return

        roster_cap = int(self.config.get("roster_cap", 53))
        current_roster = len(self.get_team_members(interaction.guild, team_name))
        if current_roster >= roster_cap:
            await interaction.response.send_message(f"{team_name} has reached the roster cap ({roster_cap}).", ephemeral=True)
            return

        class OfferView(discord.ui.View):
            def __init__(self, bot, player, team_role, team_name, team_emoji, coach_role):
                super().__init__(timeout=86400)  # 24 hours
                self.bot = bot
                self.player = player
                self.team_role = team_role
                self.team_name = team_name
                self.team_emoji = team_emoji
                self.coach_role = coach_role

            async def on_timeout(self):
                self.stop()

            @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
            async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != self.player:
                    await interaction.response.send_message("Only the offered player can accept.", ephemeral=True)
                    return
                try:
                    await self.player.add_roles(self.team_role)
                    current_roster = len(self.bot.get_cog("TransactionsCog").get_team_members(interaction.guild, self.team_name))
                    embed = discord.Embed(
                        title="Offer Accepted",
                        description=f"{self.player.mention} has accepted the offer to join {self.team_emoji} {self.team_name}",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    if interaction.guild.icon:
                        embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
                    embed.add_field(name="Coach:", value=f"{self.coach_role} {interaction.user.mention}", inline=False)
                    embed.add_field(name="Roster:", value=f"{current_roster}/{roster_cap}", inline=False)
                    if self.team_emoji:
                        embed.set_thumbnail(url=self.team_emoji)  # Full-size team emoji
                    # Send to transactions channel from guild-specific setup
                    guild_config = self.bot.get_cog("TransactionsCog").get_guild_config(interaction.guild.id)
                    transactions_channel_id = guild_config.get("channels", {}).get("transactions")
                    if transactions_channel_id:
                        transactions_channel = interaction.guild.get_channel(int(transactions_channel_id))
                        if transactions_channel:
                            await transactions_channel.send(embed=embed)
                    await interaction.response.send_message("Contract accepted!", ephemeral=True)
                    await self.bot.get_cog("TransactionsCog").log_action(
                        interaction.guild,
                        "Contract Accepted",
                        f"{self.player.display_name} joined {self.team_name}"
                    )
                    self.stop()
                except discord.errors.HTTPException as e:
                    await interaction.response.send_message(f"Failed to accept contract: {e}", ephemeral=True)

            @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
            async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != self.player:
                    await interaction.response.send_message("Only the offered player can decline.", ephemeral=True)
                    return
                await interaction.response.send_message("Contract declined.", ephemeral=True)
                await self.bot.get_cog("TransactionsCog").log_action(
                    interaction.guild,
                    "Contract Declined",
                    f"{self.player.display_name} declined {self.team_name}"
                )
                self.stop()

        view = OfferView(self.bot, player, team_role, team_name, team_emoji, self.get_franchise_role(interaction.user))
        embed = discord.Embed(
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
            if interaction.guild.icon:
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
            embed.add_field(name="Roster:", value=f"{current_roster - 1}/{int(self.config.get('roster_cap', 53))}", inline=False)
            if team_emoji:
                embed.set_thumbnail(url=team_emoji)  # Full-size team emoji
            demands_channel_id = self.config.get("demands_channel")
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
            if interaction.guild.icon:
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
            embed.add_field(name="Coach:", value=f"{coach_role} {interaction.user.mention}", inline=False)
            if team_emoji:
                embed.set_thumbnail(url=team_emoji)  # Full-size team emoji
            transactions_channel_id = self.config.get("transactions_channel")
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
            if interaction.guild.icon:
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
            embed.add_field(name="Coach:", value=f"{coach_role} {interaction.user.mention}", inline=False)
            if team_emoji:
                embed.set_thumbnail(url=team_emoji)  # Full-size team emoji
            transactions_channel_id = self.config.get("transactions_channel")
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

        if not self.check_trade_deadline():
            await interaction.response.send_message("The trade deadline has passed.", ephemeral=True)
            return

        team_role, user_team, team_emoji = self.get_team_info(interaction.user)
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

        roster_cap = int(self.config.get("roster_cap", 53))
        user_roster = len(self.get_team_members(interaction.guild, user_team))
        targeted_roster = len(self.get_team_members(interaction.guild, targeted_team))
        if user_roster >= roster_cap or targeted_roster >= roster_cap:
            await interaction.response.send_message("One or both teams are at roster cap.", ephemeral=True)
            return

        target_team_emoji = self.team_emojis.get(targeted_team, "")
        embed = discord.Embed(
            title="Trade Proposal",
            description=f"Trade proposed by {team_emoji} {user_team}:",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        embed.add_field(name=f"{team_emoji} {user_team} Offers", value=offered_player.mention, inline=False)
        embed.add_field(name=f"{target_team_emoji} {targeted_team} Offers", value=targeted_player.mention, inline=False)

        class TradeView(discord.ui.View):
            def __init__(self, bot, user_team, targeted_team, offered_player, targeted_player, team_emoji, target_team_emoji):
                super().__init__(timeout=86400)  # 24 hours
                self.bot = bot
                self.user_team = user_team
                self.targeted_team = targeted_team
                self.offered_player = offered_player
                self.targeted_player = targeted_player
                self.team_emoji = team_emoji
                self.target_team_emoji = target_team_emoji
                self.user_fo = discord.utils.get(interaction.guild.roles, name="Franchise Owner")
                self.target_fo = None

            async def start(self):
                target_team_role = discord.utils.get(interaction.guild.roles, name=self.targeted_team)
                self.target_fo = None
                for member in interaction.guild.members:
                    if self.user_fo in member.roles and target_team_role in member.roles:
                        self.target_fo = member
                        break
                if not self.target_fo:
                    await interaction.followup.send("No Franchise Owner found for the targeted team.", ephemeral=True)
                    self.stop()
                    return
                thread = await interaction.channel.create_thread(
                    name=f"Trade: {self.user_team} vs {self.targeted_team}",
                    message=await interaction.original_response(),
                    auto_archive_duration=60
                )
                await thread.send(content=f"{interaction.user.mention} {self.target_fo.mention}", embed=embed)

            @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
            async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user not in [interaction.user, self.target_fo]:
                    await interaction.response.send_message("Only the proposing or target Franchise Owner can approve.", ephemeral=True)
                    return
                if interaction.user == interaction.user and self.user_team_approved:
                    await interaction.response.send_message("You have already approved this trade.", ephemeral=True)
                    return
                if interaction.user == self.target_fo and self.target_team_approved:
                    await interaction.response.send_message("You have already approved this trade.", ephemeral=True)
                    return

                if interaction.user == interaction.user:
                    self.user_team_approved = True
                else:
                    self.target_team_approved = True

                if self.user_team_approved and self.target_team_approved:
                    user_team_role = discord.utils.get(interaction.guild.roles, name=self.user_team)
                    targeted_team_role = discord.utils.get(interaction.guild.roles, name=self.targeted_team)
                    try:
                        await self.offered_player.remove_roles(user_team_role)
                        await self.offered_player.add_roles(targeted_team_role)
                        await self.targeted_player.remove_roles(targeted_team_role)
                        await self.targeted_player.add_roles(user_team_role)
                        embed.title = "Trade Accepted"
                        embed.color = discord.Color.green()
                        embed.description = f"{self.target_team_emoji} {self.targeted_team} has accepted a trade from {self.team_emoji} {self.user_team}"
                        embed.add_field(name=f"{self.team_emoji} {self.user_team} Receives", value=self.targeted_player.mention, inline=False)
                        embed.add_field(name=f"{self.target_team_emoji} {self.targeted_team} Receives", value=self.offered_player.mention, inline=False)
                        await interaction.message.edit(embed=embed, view=None)
                        transactions_channel_id = self.bot.get_cog("TransactionsCog").config.get("transactions_channel")
                        transactions_channel = interaction.guild.get_channel(int(transactions_channel_id)) if transactions_channel_id else interaction.channel
                        await transactions_channel.send(embed=embed)
                        await interaction.response.send_message("Trade completed!", ephemeral=True)
                        await self.bot.get_cog("TransactionsCog").log_action(
                            interaction.guild,
                            "Trade Completed",
                            f"{self.offered_player.display_name} to {self.targeted_team}, {self.targeted_player.display_name} to {self.user_team}"
                        )
                    except discord.errors.HTTPException as e:
                        await interaction.response.send_message(f"Failed to execute trade: {e}", ephemeral=True)
                else:
                    await interaction.response.send_message("Trade approved. Waiting for other team.", ephemeral=True)

            @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
            async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user not in [interaction.user, self.target_fo]:
                    await interaction.response.send_message("Only the proposing or target Franchise Owner can reject.", ephemeral=True)
                    return
                embed.title = "Trade Rejected"
                embed.description += f"\nRejected by {interaction.user.mention}"
                embed.color = discord.Color.red()
                await interaction.message.edit(embed=embed, view=None)
                await interaction.response.send_message("Trade rejected.", ephemeral=True)
                await self.bot.get_cog("TransactionsCog").log_action(
                    interaction.guild,
                    "Trade Rejected",
                    f"Rejected by {interaction.user.display_name}"
                )
                self.stop()

        view = TradeView(self.bot, user_team, targeted_team, offered_player, targeted_player, team_emoji, target_team_emoji)
        await view.start()
        await interaction.response.send_message("Trade proposal started in a thread!", ephemeral=True)
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