import discord
from discord import app_commands
from discord.ext import commands
import json
import random
import os
from datetime import datetime
import pytz
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
    return {
        "draft_active": False,
        "draft_paused": False,
        "current_round": 0,
        "current_pick": 0,
        "draft_order": [],
        "autopick_settings": {},
        "picks": []
    }

def save_draft(draft_data):
    with open(DRAFT_FILE, 'w') as f:
        json.dump(draft_data, f, indent=4)

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

class DraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()
        self.team_emojis = self.config.get("team_emojis", {})
        self.draft_data = load_draft()

    async def log_action(self, guild, action, details):
        logs_channel_id = self.config.get("logs_channel")
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Draft: {action}",
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

    # CPU Break: Pause after cog initialization
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="startdraft", description="Start a new draft.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(rounds="Number of draft rounds", picks_per_round="Picks per round")
    async def startdraft(self, interaction: discord.Interaction, rounds: int, picks_per_round: int):
        if self.draft_data.get("draft_active", False):
            await interaction.response.send_message("A draft is already active.", ephemeral=True)
            return
        if rounds < 1 or picks_per_round < 1:
            await interaction.response.send_message("Rounds and picks per round must be positive.", ephemeral=True)
            return
        if picks_per_round > len(self.config.get("teams", [])):
            await interaction.response.send_message("Picks per round cannot exceed number of teams.", ephemeral=True)
            return

        teams = self.config.get("teams", [])
        draft_order = teams * rounds
        random.shuffle(draft_order)

        self.draft_data = {
            "draft_active": True,
            "draft_paused": False,
            "current_round": 1,
            "current_pick": 1,
            "total_rounds": rounds,
            "picks_per_round": picks_per_round,
            "draft_order": draft_order,
            "autopick_settings": {team: [] for team in teams},  # Initialize empty lists for autopick preferences
            "picks": []
        # Store draft picks
        }
        save_draft(self.draft_data)

        current_team = draft_order[0] if draft_order else teams[0]
        team_emoji = self.team_emojis.get(current_team, "")
        embed = discord.Embed(
            title="Draft Started",
            description=f"The draft has begun! {team_emoji} {current_team} is on the clock for Round 1, Pick 1.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="Total Rounds", value=str(rounds), inline=True)
        embed.add_field(name="Picks per Round", value=str(picks_per_round), inline=True)
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        alerts_channel_id = self.config.get("alerts_channel")
        alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
        await alerts_channel.send(embed=embed)
        await interaction.response.send_message("Draft started!", ephemeral=True)
        await self.log_action(interaction.guild, "Draft Started", f"Rounds: {rounds}, Picks per Round: {picks_per_round}")

    # CPU Break: Pause after /startdraft
    @app_commands.command()
    async def enddraft(self, interaction: discord.Interaction):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            return

        async def enddraft_callback(interaction: discord.Interaction):
            self.draft_data = {
                "draft_active": False,
                "draft_paused": False,
                "current_round": 0,
                "current_pick": 0,
                "draft_order": [],
                "autopick_settings": {},
                "picks": self.draft_data.get("picks", [])
            }
            save_draft(self.draft_data)
            embed = discord.Embed(
                title="Draft Ended",
                description="The draft has been terminated.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            alerts_channel_id = self.config.get("alerts_channel")
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
            await alerts_channel.send(embed=embed)
            await interaction.response.send_message("Draft ended!", ephemeral=True)
            await self.log_action(interaction.guild, "Draft Ended", "Draft terminated")

        modal = ConfirmModal("End Draft", enddraft_callback)
        await interaction.response.send_modal(modal)

    @app_commands.command()
    async def pausedraft(self, interaction: discord.Interaction):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            return
        if self.draft_data.get("draft_paused", True):
            await interaction.response.send_message("The draft is already paused.", ephemeral=True)
            return

        self.draft_data["draft_paused"] = True
        save_draft(self.draft_data)
        embed = discord.Embed(
            title="Draft Paused",
            description="The draft has been paused.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        alerts_channel_id = self.config.get("alerts_channel")
        alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
        await alerts_channel.send(embed=embed)
        await interaction.response.send_message("Draft paused.", ephemeral=True)
        await self.log_action(interaction.guild, "Draft Paused", "Draft paused")

    @app_commands.command()
    async def resumedraft(self, interaction: discord.Interaction):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            return
        if not self.draft_data.get("draft_paused", False):
            await interaction.response.send_message("The draft is not paused.", ephemeral=True)
            return

        self.draft_data["draft_paused"] = False
        save_draft(self.draft_data)
        current_team = self.draft_data["draft_order"][
            (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
        ]
        team_emoji = self.team_emojis.get(current_team, "")
        embed = discord.Embed(
            title="Draft Resumed",
            description=f"The draft has resumed. {team_emoji} {current_team} is on the clock for Round {self.draft_data['current_round']}, Pick {self.draft_data['current_pick']}.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        alerts_channel_id = self.config.get("alerts_channel")
        alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
        await alerts_channel.send(embed=embed)
        await interaction.response.send_message("Draft resumed!", ephemeral=True)
        await self.log_action(interaction.guild, "Draft Resumed", "Draft resumed")

    @app_commands.command()
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager")
    @app_commands.describe(player="The player to draft", team="The team making the pick")
    async def setpick(self, interaction: discord.Interaction, player: discord.Member, team: str):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft active.", ephemeral=True)
            return
        if self.draft_data.get("draft_paused", False):
            await interaction.response.send_message("The draft is paused.", ephemeral=True)
            return
        if team not in self.config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setup.", ephemeral=True)
            return

        team_role, team_name, _ = self.get_team_info(interaction.user)
        if team_name != team:
            await interaction.response.send_message(f"You can only make picks for your own team.", ephemeral=True)
            return

        current_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
        if current_index >= len(self.draft_data["draft_order"]):
            await interaction.response.send_message("Draft has ended.", ephemeral=True)
            return
        current_team = self.draft_data["draft_order"][current_index]
        if current_team != team:
            await interaction.response.send_message(f"It’s not {team}’s turn to pick.", ephemeral=True)
            return

        player_team_role, player_team, _ = self.get_team_info(player)
        if player_team:
            await interaction.response.send_message(f"{player.display_name} is already on {player_team}.", ephemeral=True)
            return

        roster_cap = int(self.config.get("roster_cap", 53))
        current_roster = len(self.get_team_members(interaction.guild, team))
        if current_roster >= roster_cap:
            await interaction.response.send_message(f"{team} has reached the roster cap ({roster_cap}).", ephemeral=True)
            return

        try:
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            await player.add_roles(team_role)
            self.draft_data["picks"].append({
                "round": self.draft_data["current_round"],
                "pick": self.draft_data["current_pick"],
                "team": team,
                "player": player.display_name,
                "player_id": str(player.id)
            })

            # Advance draft pick
            self.draft_data["current_pick"] += 1
            if self.draft_data["current_pick"] > self.draft_data["picks_per_round"]:
                self.draft_data["current_round"] += 1
                self.draft_data["current_pick"] = 1
            if self.draft_data["current_round"] > self.draft_data["total_rounds"]:
                self.draft_data["draft_active"] = False
                self.draft_data["draft_paused"] = False

            save_draft(self.draft_data)

            team_emoji = self.team_emojis.get(team, "")
            embed = discord.Embed(
                title="Draft Pick",
                description=f"{team_emoji} {team} selects {player.mention} in Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']}.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            if self.draft_data.get("draft_active", True):
                next_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
                if next_index < len(self.draft_data["draft_order"]):
                    next_team = self.draft_data["draft_order"][next_index]
                    next_emoji = self.team_emojis.get(next_team, "")
                    embed.add_field(
                        name="Next Pick",
                        value=f"{next_emoji} {next_team} is on the clock for Round {self.draft_data['current_round']}, Pick {self.draft_data['current_pick']}.",
                        inline=False
                    )
            else:
                embed.add_field(name="Draft Complete", value="The draft has concluded!", inline=False)

            alerts_channel_id = self.config.get("alerts_channel")
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
            await alerts_channel.send(embed=embed)
            await interaction.response.send_message("Pick set!", ephemeral=True)
            await self.log_action(
                interaction.guild,
                "Draft Pick",
                f"{team} picked {player.display_name} (Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']})"
            )
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to set pick: {e}", ephemeral=True)

    @app_commands.command()
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager")
    @app_commands.describe(team="The team to toggle autopick for")
    async def autopick(self, interaction: discord.Interaction, team: str):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            return
        if team not in self.config.get("teams", []):
            await interaction.response.send_message("Invalid sending team. Must be created via /setup.", ephemeral=True)
            return

        team_role, team_name, _ = self.get_team_info(interaction.user)
        if team_name != team:
            await interaction.response.send_message("You can only toggle autopick for your own team.", ephemeral=True)
            return

        self.draft_data["autopick_settings"][team] = not self.draft_data["autopick_settings"].get(team, False)
        save_draft(self.draft_data)
        status = "enabled" if self.draft_data["autopick_settings"][team] else "disabled"
        team_emoji = self.team_emojis.get(team, "")
        embed = discord.Embed(
            title="Auto-pick Updated",
            description=f"Autopick {status} for {team_emoji} {team}.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.log_action(interaction.guild, "Auto-pick Toggled", f"{team} set autopick to {status}")

    @app_commands.command()
    async def draftorder(self, interaction: discord.Interaction):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Draft Order",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        order_by_round = []
        for round_num in range(1, self.draft_data["total_rounds"] + 1):
            start_idx = (round_num - 1) * self.draft_data["picks_per_round"]
            end_idx = start_idx + self.draft_data["picks_per_round"]
            round_picks = self.draft_data["draft_order"][start_idx:end_idx]
            picks = []
            for i, team in enumerate(round_picks, 1):
                team_emoji = self.team_emojis.get(team, "")
                picks.append(f"{team_emoji} {team} (Pick {i})")
            order_by_round.append(f"**Round {round_num}**\n" + "\n".join(picks))

        embed.description = "\n\n".join(order_by_round)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.log_action(interaction.guild, "Draft Order Viewed", "Draft order requested")

    @app_commands.command()
    async def draftstatus(self, interaction: discord.Interaction):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Draft Status",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(
            name="Status",
            value="Paused" if self.draft_data.get("draft_paused", False) else "Active",
            inline=True
        )
        embed.add_field(
            name="Current Pick",
            value=f"Round {self.draft_data['current_round']}, Pick {self.draft_data['current_pick']}",
            inline=True
        )
        current_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
        if current_index < len(self.draft_data["draft_order"]):
            current_team = self.draft_data["draft_order"][current_index]
            team_emoji = self.team_emojis.get(current_team, "")
            embed.add_field(
                name="On the Clock",
                value=f"{team_emoji} {current_team}",
                inline=False
            )

        if self.draft_data["picks"]:
            picks = []
            for pick in self.draft_data["picks"]:
                team_emoji = self.team_emojis.get(pick["team"], "")
                picks.append(f"{team_emoji} {pick['team']}: {pick['player']} (Round {pick['round']}, Pick {pick['pick']})")
            embed.add_field(
                name="Picks Made",
                value="\n".join(picks)[:1024],  # Truncate if too long
                inline=False
            )
        else:
            embed.add_field(name="Picks Made", value="None", inline=False)

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)
        await self.log_action(interaction.guild, "Draft Status Viewed", "Draft status requested")

    @app_commands.command(name="draftpick", description="Make a draft pick for a team.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(team="The team making the pick", player="The player being drafted")
    @app_commands.autocomplete(team=team_autocomplete)
    async def draftpick(self, interaction: discord.Interaction, team: str, player: discord.Member):
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft active.", ephemeral=True)
            return
        if self.draft_data.get("draft_paused", False):
            await interaction.response.send_message("The draft is paused.", ephemeral=True)
            return
        if team not in self.config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setup.", ephemeral=True)
            return

        team_role, team_name, _ = self.get_team_info(interaction.user)
        if team_name != team:
            await interaction.response.send_message(f"You can only make picks for your own team.", ephemeral=True)
            return

        current_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
        if current_index >= len(self.draft_data["draft_order"]):
            await interaction.response.send_message("Draft has ended.", ephemeral=True)
            return
        current_team = self.draft_data["draft_order"][current_index]
        if current_team != team:
            await interaction.response.send_message(f"It’s not {team}’s turn to pick.", ephemeral=True)
            return

        player_team_role, player_team, _ = self.get_team_info(player)
        if player_team:
            await interaction.response.send_message(f"{player.display_name} is already on {player_team}.", ephemeral=True)
            return

        roster_cap = int(self.config.get("roster_cap", 53))
        current_roster = len(self.get_team_members(interaction.guild, team))
        if current_roster >= roster_cap:
            await interaction.response.send_message(f"{team} has reached the roster cap ({roster_cap}).", ephemeral=True)
            return

        try:
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            await player.add_roles(team_role)
            self.draft_data["picks"].append({
                "round": self.draft_data["current_round"],
                "pick": self.draft_data["current_pick"],
                "team": team,
                "player": player.display_name,
                "player_id": str(player.id)
            })

            # Advance draft pick
            self.draft_data["current_pick"] += 1
            if self.draft_data["current_pick"] > self.draft_data["picks_per_round"]:
                self.draft_data["current_round"] += 1
                self.draft_data["current_pick"] = 1
            if self.draft_data["current_round"] > self.draft_data["total_rounds"]:
                self.draft_data["draft_active"] = False
                self.draft_data["draft_paused"] = False

            save_draft(self.draft_data)

            team_emoji = self.team_emojis.get(team, "")
            embed = discord.Embed(
                title="Draft Pick",
                description=f"{team_emoji} {team} selects {player.mention} in Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']}.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            if self.draft_data.get("draft_active", True):
                next_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
                if next_index < len(self.draft_data["draft_order"]):
                    next_team = self.draft_data["draft_order"][next_index]
                    next_emoji = self.team_emojis.get(next_team, "")
                    embed.add_field(
                        name="Next Pick",
                        value=f"{next_emoji} {next_team} is on the clock for Round {self.draft_data['current_round']}, Pick {self.draft_data['current_pick']}.",
                        inline=False
                    )
            else:
                embed.add_field(name="Draft Complete", value="The draft has concluded!", inline=False)

            alerts_channel_id = self.config.get("alerts_channel")
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
            await alerts_channel.send(embed=embed)
            await interaction.response.send_message("Pick set!", ephemeral=True)
            await self.log_action(
                interaction.guild,
                "Draft Pick",
                f"{team} picked {player.display_name} (Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']})"
            )
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to set pick: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(DraftCog(bot))