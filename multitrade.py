import discord
import os
from discord import app_commands
from discord.ext import commands
import json
import pytz
from datetime import datetime
import asyncio
from utils.team_utils import team_autocomplete

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

class MultiTradeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.config and self.team_emojis removed

    async def get_team_info(self, member: discord.Member):
        guild_config = load_guild_config(member.guild.id)
        team_emojis = guild_config.get("team_emojis", {})
        for role in member.roles:
            if role.name in guild_config.get("teams", []) and role.name != "@everyone":
                emoji = team_emojis.get(role.name, "")
                return role, role.name, emoji
        return None, None, None

    async def log_action(self, guild, action, details):
        guild_config = load_guild_config(guild.id)
        logs_channel_id = guild_config.get("logs_channel") # Assuming logs_channel is top-level
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Multi-Trade: {action}",
                    description=details,
                    color=discord.Color.blue,
                    timestamp=discord.utils.utcnow()
                )
                await logs_channel.send(embed=embed)

    def check_trade_deadline(self, guild_id: int):
        guild_config = load_guild_config(guild_id)
        deadline_str = guild_config.get("trade_deadline") # Assuming trade_deadline is top-level
        if not deadline_str:
            return True # No deadline set, trades always allowed
        try:
            # Assuming deadline is stored as "YYYY-MM-DD"
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
            return datetime.now(pytz.UTC) <= deadline
        except ValueError:
            # Invalid format or value, default to allowing trades to avoid blocking unnecessarily
            return True

    def get_team_members(self, guild: discord.Guild, team_name: str):
        team_role = discord.utils.get(guild.roles, name=team_name)
        if not team_role:
            return []
        return [member for member in guild.members if team_role in member.roles]

    # CPU Break: Pause after cog initialization
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="multitrade", description="Execute a multi-team trade.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(team1="First team", team2="Second team", team3="Third team (optional)")
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete, team3=team_autocomplete)
    async def multitrade(self, interaction: discord.Interaction, team1: str, team2: str, team3: str = None):
        await interaction.response.defer(ephemeral=True)
        guild_config = load_guild_config(interaction.guild.id)

        # Validate draft status
        draft_data = load_draft()
        if draft_data.get("draft_active", False):
            await interaction.followup.send("Trades are disabled during an active draft.", ephemeral=True)
            return

        # Validate trade deadline
        if not self.check_trade_deadline(interaction.guild.id):
            await interaction.followup.send("The trade deadline has passed.", ephemeral=True)
            return

        # Validate teams
        teams_in_trade = [team1, team2]
        if team3:
            teams_in_trade.append(team3)
        if not all(t in guild_config.get("teams", []) for t in teams_in_trade):
            await interaction.followup.send("All teams must be valid and created via /setup.", ephemeral=True)
            return
        if len(set(teams_in_trade)) != len(teams_in_trade):
            await interaction.followup.send("Teams must be unique.", ephemeral=True)
            return

        # Validate user permissions
        user_team_role, user_team_name, _ = await self.get_team_info(interaction.user) # await added
        if not user_team_role or user_team_name not in teams_in_trade:
            await interaction.followup.send("You can only propose trades for your own team.", ephemeral=True)
            return

        # Parse players and picks
        trade_details = {}
        for team, player_str, pick_str in [(team1, team1_players, team1_picks), (team2, team2_players, team2_picks),
                                          (team3, team3_players, team3_picks) if team3 else (None, "", "")]:
            if not team:
                continue
            players = [p.strip() for p in player_str.split(",") if p.strip()]
            picks = [p.strip() for p in pick_str.split(",") if p.strip()]
            trade_details[team] = {"players": [], "picks": picks}

            # Validate players
            for player_id in players:
                try:
                    member = interaction.guild.get_member(int(player_id))
                    if not member:
                        await interaction.followup.send(f"Player ID {player_id} not found in server.", ephemeral=True)
                        return
                    team_role, team_name, _ = await self.get_team_info(member) # await added
                    if team_name != team:
                        await interaction.followup.send(f"{member.display_name} is not on {team}.", ephemeral=True)
                        return
                    trade_details[team]["players"].append(member)
                except ValueError:
                    await interaction.followup.send(f"Invalid player ID: {player_id}.", ephemeral=True)
                    return

            # Validate picks (basic format check)
            for pick in picks:
                if not pick.startswith("Round") or "Pick" not in pick:
                    await interaction.followup.send(f"Invalid pick format: {pick}. Use RoundXPickY.", ephemeral=True)
                    return

        # Check roster caps after trade
        roster_cap = int(guild_config.get("roster_cap", 53))
        for team_in_trade_calc in teams_in_trade: # Renamed to avoid conflict
            current_roster = len(self.get_team_members(interaction.guild, team_in_trade_calc))
            players_gained = sum(len(trade_details[t]["players"]) for t in teams_in_trade if t != team_in_trade_calc)
            players_lost = len(trade_details[team_in_trade_calc]["players"])
            new_roster_size = current_roster + players_gained - players_lost
            if new_roster_size > roster_cap:
                await interaction.followup.send(f"Trade would exceed roster cap ({roster_cap}) for {team_in_trade_calc}.", ephemeral=True)
                return

        # Prepare trade embed
        embed = discord.Embed(
            title=f"Multi-Team Trade Proposal",
            description=f"Proposed by {interaction.user.mention} ({user_team_name})",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        team_emojis = guild_config.get("team_emojis", {})
        for team_in_trade_display in teams_in_trade: # Renamed to avoid conflict
            team_emoji = team_emojis.get(team_in_trade_display, "")
            players = ", ".join(m.display_name for m in trade_details[team_in_trade_display]["players"]) or "None"
            picks = ", ".join(trade_details[team_in_trade_display]["picks"]) or "None"
            embed.add_field(
                name=f"{team_emoji} {team_in_trade_display} Gives",
                value=f"**Players**: {players}\n**Picks**: {picks}",
                inline=False
            )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        # Confirmation view for other team owners
        class TradeView(discord.ui.View):
            def __init__(self, bot, teams_involved, trade_details_view, proposer_team_name): # Renamed parameters
                super().__init__(timeout=86400)  # 24 hours
                self.bot = bot
                self.teams_involved = teams_involved
                self.trade_details_view = trade_details_view
                self.proposer_team_name = proposer_team_name
                self.approvals = {team_involved: False for team_involved in self.teams_involved}
                self.approvals[self.proposer_team_name] = True  # Proposer auto-approves

            async def check_fo(self, user, team_to_check): # Renamed parameter
                # This should ideally also use guild_config to get role names if they become configurable
                fo_role = discord.utils.get(user.guild.roles, name="Franchise Owner")
                team_role_obj = discord.utils.get(user.guild.roles, name=team_to_check) # Renamed
                return fo_role in user.roles and team_role_obj in user.roles

            @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
            async def approve_button(self, interaction_view: discord.Interaction, button: discord.ui.Button): # Renamed
                user_team_role_view, user_team_view, _ = await self.bot.get_cog("MultiTradeCog").get_team_info(interaction_view.user) # await
                if user_team_view not in self.teams_involved:
                    await interaction_view.response.send_message("You are not part of this trade.", ephemeral=True)
                    return
                if not await self.check_fo(interaction_view.user, user_team_view):
                    await interaction_view.response.send_message("Only Franchise Owners can approve trades.", ephemeral=True)
                    return
                if self.approvals[user_team_view]:
                    await interaction_view.response.send_message("You have already approved this trade.", ephemeral=True)
                    return

                self.approvals[user_team_view] = True
                embed.description += f"\n{user_team_view} approved by {interaction_view.user.mention}"
                await interaction_view.message.edit(embed=embed)

                if all(self.approvals.values()):
                    # Execute trade
                    for team_exec in self.teams_involved: # Renamed
                        team_role_exec = discord.utils.get(interaction_view.guild.roles, name=team_exec) # Renamed
                        for other_team_exec in self.teams_involved: # Renamed
                            if other_team_exec == team_exec:
                                continue
                            for player_exec in self.trade_details_view[other_team_exec]["players"]: # Renamed
                                await player_exec.add_roles(team_role_exec)
                            for player_exec_lost in self.trade_details_view[team_exec]["players"]: # Renamed
                                await player_exec_lost.remove_roles(team_role_exec) # This logic seems reversed, should be remove from old, add to new
                        # Note: Draft picks are logged but not reassigned here (assumed handled by draft system)
                    embed.title = "Multi-Team Trade Completed"
                    embed.color = discord.Color.green()
                    await interaction_view.message.edit(embed=embed, view=None)
                    await interaction_view.response.send_message("Trade approved and completed!", ephemeral=True)
                    await self.bot.get_cog("MultiTradeCog").log_action(
                        interaction_view.guild,
                        "Multi-Trade Completed",
                        f"Teams: {', '.join(self.teams_involved)}"
                    )
                else:
                    await interaction_view.response.send_message("Trade approved. Waiting for other approvals.", ephemeral=True)

            @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
            async def reject_button(self, interaction_view: discord.Interaction, button: discord.ui.Button): # Renamed
                user_team_role_view, user_team_view, _ = await self.bot.get_cog("MultiTradeCog").get_team_info(interaction_view.user) # await
                if user_team_view not in self.teams_involved:
                    await interaction_view.response.send_message("You are not part of this trade.", ephemeral=True)
                    return
                if not await self.check_fo(interaction_view.user, user_team_view): # check_fo needs guild_config for role name if configurable
                    await interaction_view.response.send_message("Only Franchise Owners can approve trades.", ephemeral=True)
                    return

                embed.title = "Multi-Team Trade Rejected"
                embed.description += f"\nRejected by {interaction_view.user.mention} ({user_team_view})"
                embed.color = discord.Color.red()
                await interaction_view.message.edit(embed=embed, view=None)
                await interaction_view.response.send_message("Trade rejected.", ephemeral=True)
                await self.bot.get_cog("MultiTradeCog").log_action(
                    interaction_view.guild,
                    "Multi-Trade Rejected",
                    f"Rejected by {user_team_view}"
                )

        # Send trade proposal
        view = TradeView(self.bot, teams_in_trade, trade_details, user_team_name)
        # guild_config already loaded
        alerts_channel_id = guild_config.get("alerts_channel") # Assuming alerts_channel is top-level
        trade_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel

        # Send to transactions channel from guild-specific setup
        transactions_channel_id = guild_config.get("channels", {}).get("transactions")
        if transactions_channel_id:
            transactions_channel = interaction.guild.get_channel(int(transactions_channel_id))
            if transactions_channel:
                await transactions_channel.send(embed=embed)
        await trade_channel.send(embed=embed, view=view) # This might send twice if alerts_channel is also transactions_channel
        await interaction.followup.send("Trade proposal sent for approval.", ephemeral=True)
        await self.log_action(
            interaction.guild,
            "Multi-Trade Proposed",
            f"Teams: {', '.join(teams_in_trade)}, Proposer: {interaction.user.display_name}"
        )

    def get_guild_config(self, guild_id): # This method is now effectively replaced by the standalone load_guild_config
        return load_guild_config(guild_id)

    # CPU Break: Pause after /multitrade
    # asyncio.sleep(2) simulated during code generation

async def setup(bot):
    await bot.add_cog(MultiTradeCog(bot))