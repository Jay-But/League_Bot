import discord
import os
from discord import app_commands
from discord.ext import commands
import json
import pytz
from datetime import datetime
import asyncio
from utils.team_utils import team_autocomplete

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

class MultiTradeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()
        self.team_emojis = self.config.get("team_emojis", {})

    async def get_team_info(self, member: discord.Member):
        for role in member.roles:
            if role.name in self.config.get("teams", []) and role.name != "@everyone":
                emoji = self.team_emojis.get(role.name, "")
                return role, role.name, emoji
        return None, None, None

    async def log_action(self, guild, action, details):
        logs_channel_id = self.config.get("logs_channel")
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

    def check_trade_deadline(self):
        deadline_str = self.config.get("trade_deadline")
        if not deadline_str:
            return True
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
            return datetime.now(pytz.UTC) <= deadline
        except ValueError:
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

        # Validate draft status
        draft_data = load_draft()
        if draft_data.get("draft_active", False):
            await interaction.followup.send("Trades are disabled during an active draft.", ephemeral=True)
            return

        # Validate trade deadline
        if not self.check_trade_deadline():
            await interaction.followup.send("The trade deadline has passed.", ephemeral=True)
            return

        # Validate teams
        teams = [team1, team2]
        if team3:
            teams.append(team3)
        if not all(t in self.config.get("teams", []) for t in teams):
            await interaction.followup.send("All teams must be valid and created via /setup.", ephemeral=True)
            return
        if len(set(teams)) != len(teams):
            await interaction.followup.send("Teams must be unique.", ephemeral=True)
            return

        # Validate user permissions
        user_team_role, user_team_name, _ = self.get_team_info(interaction.user)
        if not user_team_role or user_team_name not in teams:
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
                    team_role, team_name, _ = self.get_team_info(member)
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
        roster_cap = int(self.config.get("roster_cap", 53))
        for team in teams:
            current_roster = len(self.get_team_members(interaction.guild, team))
            players_gained = sum(len(trade_details[t]["players"]) for t in teams if t != team)
            players_lost = len(trade_details[team]["players"])
            new_roster_size = current_roster + players_gained - players_lost
            if new_roster_size > roster_cap:
                await interaction.followup.send(f"Trade would exceed roster cap ({roster_cap}) for {team}.", ephemeral=True)
                return

        # Prepare trade embed
        embed = discord.Embed(
            title=f"Multi-Team Trade Proposal",
            description=f"Proposed by {interaction.user.mention} ({user_team_name})",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        for team in teams:
            team_emoji = self.team_emojis.get(team, "")
            players = ", ".join(m.display_name for m in trade_details[team]["players"]) or "None"
            picks = ", ".join(trade_details[team]["picks"]) or "None"
            embed.add_field(
                name=f"{team_emoji} {team} Gives",
                value=f"**Players**: {players}\n**Picks**: {picks}",
                inline=False
            )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        # Confirmation view for other team owners
        class TradeView(discord.ui.View):
            def __init__(self, bot, teams, trade_details, proposer):
                super().__init__(timeout=86400)  # 24 hours
                self.bot = bot
                self.teams = teams
                self.trade_details = trade_details
                self.proposer = proposer
                self.approvals = {team: False for team in teams}
                self.approvals[proposer] = True  # Proposer auto-approves

            async def check_fo(self, user, team):
                fo_role = discord.utils.get(user.guild.roles, name="Franchise Owner")
                team_role = discord.utils.get(user.guild.roles, name=team)
                return fo_role in user.roles and team_role in user.roles

            @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
            async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                user_team_role, user_team, _ = self.bot.get_cog("MultiTradeCog").get_team_info(interaction.user)
                if user_team not in self.teams:
                    await interaction.response.send_message("You are not part of this trade.", ephemeral=True)
                    return
                if not await self.check_fo(interaction.user, user_team):
                    await interaction.response.send_message("Only Franchise Owners can approve trades.", ephemeral=True)
                    return
                if self.approvals[user_team]:
                    await interaction.response.send_message("You have already approved this trade.", ephemeral=True)
                    return

                self.approvals[user_team] = True
                embed.description += f"\n{user_team} approved by {interaction.user.mention}"
                await interaction.message.edit(embed=embed)

                if all(self.approvals.values()):
                    # Execute trade
                    for team in self.teams:
                        team_role = discord.utils.get(interaction.guild.roles, name=team)
                        for other_team in self.teams:
                            if other_team == team:
                                continue
                            for player in self.trade_details[other_team]["players"]:
                                await player.add_roles(team_role)
                            for player in self.trade_details[team]["players"]:
                                await player.remove_roles(team_role)
                        # Note: Draft picks are logged but not reassigned here (assumed handled by draft system)
                    embed.title = "Multi-Team Trade Completed"
                    embed.color = discord.Color.green()
                    await interaction.message.edit(embed=embed, view=None)
                    await interaction.response.send_message("Trade approved and completed!", ephemeral=True)
                    await self.bot.get_cog("MultiTradeCog").log_action(
                        interaction.guild,
                        "Multi-Trade Completed",
                        f"Teams: {', '.join(self.teams)}"
                    )
                else:
                    await interaction.response.send_message("Trade approved. Waiting for other approvals.", ephemeral=True)

            @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
            async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                user_team_role, user_team, _ = self.bot.get_cog("MultiTradeCog").get_team_info(interaction.user)
                if user_team not in self.teams:
                    await interaction.response.send_message("You are not part of this trade.", ephemeral=True)
                    return
                if not await self.check_fo(interaction.user, user_team):
                    await interaction.response.send_message("Only Franchise Owners can approve trades.", ephemeral=True)
                    return

                embed.title = "Multi-Team Trade Rejected"
                embed.description += f"\nRejected by {interaction.user.mention} ({user_team})"
                embed.color = discord.Color.red()
                await interaction.message.edit(embed=embed, view=None)
                await interaction.response.send_message("Trade rejected.", ephemeral=True)
                await self.bot.get_cog("MultiTradeCog").log_action(
                    interaction.guild,
                    "Multi-Trade Rejected",
                    f"Rejected by {user_team}"
                )

        # Send trade proposal
        view = TradeView(self.bot, teams, trade_details, user_team_name)
        trade_channel_id = self.config.get("alerts_channel")
        trade_channel = interaction.guild.get_channel(int(trade_channel_id)) if trade_channel_id else interaction.channel

        # Send to transactions channel from guild-specific setup
        guild_config = self.get_guild_config(interaction.guild.id)
        transactions_channel_id = guild_config.get("channels", {}).get("transactions")
        if transactions_channel_id:
            transactions_channel = interaction.guild.get_channel(int(transactions_channel_id))
            if transactions_channel:
                await transactions_channel.send(embed=embed)
        await trade_channel.send(embed=embed, view=view)
        await interaction.followup.send("Trade proposal sent for approval.", ephemeral=True)
        await self.log_action(
            interaction.guild,
            "Multi-Trade Proposed",
            f"Teams: {', '.join(teams)}, Proposer: {interaction.user.display_name}"
        )
    def get_guild_config(self, guild_id):
        guild_id_str = str(guild_id)
        if guild_id_str in self.config:
            return self.config[guild_id_str]
        else:
            return {}

    # CPU Break: Pause after /multitrade
    # asyncio.sleep(2) simulated during code generation

async def setup(bot):
    await bot.add_cog(MultiTradeCog(bot))