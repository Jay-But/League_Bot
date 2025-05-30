import discord
from discord import app_commands
from discord.ext import commands
import json
import random
import os
from datetime import datetime
import pytz
from utils.team_utils import team_autocomplete
from datetime import timezone # Added, datetime already imported

# Logger utility code
LOG_DIR = "guild_logs"

def ensure_log_dir():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

def format_log_message(user: discord.User | discord.Member, command_name: str, outcome: str, details: dict) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    user_info = f"{user.name}#{user.discriminator} ({user.id})"
    if command_name.startswith('/'):
        display_command_name = command_name
    else:
        display_command_name = f"/{command_name}"

    details_str_parts = []
    for k, v in details.items():
        if isinstance(v, str) and len(v) > 75:
            details_str_parts.append(f"{k}={v[:75]}...")
        else:
            details_str_parts.append(f"{k}={v}")
    details_str = ", ".join(details_str_parts)

    return f"[{timestamp}] [User: {user_info}] [Command: {display_command_name}] [Outcome: {outcome}] Details: {{{details_str}}}"

def log_command(interaction: discord.Interaction, command_name: str, outcome: str, **details) -> None:
    ensure_log_dir()
    if interaction.guild:
        guild_id = str(interaction.guild.id)
    else:
        guild_id = "dm_logs"
    log_file_path = os.path.join(LOG_DIR, f"{guild_id}.log")

    user = interaction.user
    message = format_log_message(user, command_name, outcome, details)

    try:
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(message + "\n")
    except Exception as e:
        print(f"Error writing to guild log {log_file_path}: {e}")

DRAFT_FILE = "config/draft.json"

def load_guild_config(guild_id):
    config_file = f"config/setup_{str(guild_id)}.json"
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            return json.load(f)
    return {}

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
        self.draft_data = load_draft()

    async def log_action(self, interaction: discord.Interaction, action, details):
        guild_config = load_guild_config(interaction.guild.id)
        logs_channel_id = guild_config.get("logs_channel")
        if logs_channel_id:
            logs_channel = interaction.guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Draft: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                await logs_channel.send(embed=embed)

    def get_team_info(self, guild_config: dict, member: discord.Member):
        team_emojis = guild_config.get("team_emojis", {})
        for role in member.roles:
            if role.name in guild_config.get("teams", []) and role.name != "@everyone":
                emoji = team_emojis.get(role.name, "")
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
        guild_config = load_guild_config(interaction.guild.id)
        command_name = "/startdraft" # Prepare for logging

        if self.draft_data.get("draft_active", False):
            await interaction.response.send_message("A draft is already active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: A draft is already active", rounds=rounds, picks_per_round=picks_per_round)
            return
        if rounds < 1 or picks_per_round < 1:
            await interaction.response.send_message("Rounds and picks per round must be positive.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Rounds/picks must be positive", rounds=rounds, picks_per_round=picks_per_round)
            return

        teams_list = guild_config.get("teams", []) # Renamed to avoid conflict
        if picks_per_round > len(teams_list):
            await interaction.response.send_message("Picks per round cannot exceed number of teams.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Picks per round exceeds number of teams", rounds=rounds, picks_per_round=picks_per_round, team_count=len(teams_list))
            return

        teams = teams_list
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
        team_emojis = guild_config.get("team_emojis", {})
        team_emoji = team_emojis.get(current_team, "")
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
        alerts_channel_id = guild_config.get("alerts_channel")
        alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
        await alerts_channel.send(embed=embed)
        await interaction.response.send_message("Draft started!", ephemeral=True)
        # self.log_action is for embed logs to a channel, log_command is for file logs
        log_command(interaction, command_name, "Draft started successfully", rounds=rounds, picks_per_round=picks_per_round)
        # Awaiting self.log_action is fine if it's meant to be an additional in-channel log
        await self.log_action(interaction, "Draft Started", f"Rounds: {rounds}, Picks per Round: {picks_per_round}")


    # CPU Break: Pause after /startdraft
    @app_commands.command()
    async def enddraft(self, interaction: discord.Interaction):
        command_name = "/enddraft"
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active")
            return

        async def enddraft_callback(callback_interaction: discord.Interaction): # Renamed interaction
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
            guild_config = load_guild_config(interaction.guild.id)
            alerts_channel_id = guild_config.get("alerts_channel")
            alerts_channel = callback_interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else callback_interaction.channel
            await alerts_channel.send(embed=embed)
            await callback_interaction.response.send_message("Draft ended!", ephemeral=True)
            log_command(callback_interaction, command_name, "Draft ended successfully by admin")
            # Awaiting self.log_action is fine if it's meant to be an additional in-channel log
            await self.log_action(callback_interaction, "Draft Ended", "Draft terminated")


        modal = ConfirmModal("End Draft", enddraft_callback)
        await interaction.response.send_modal(modal)

    @app_commands.command()
    async def pausedraft(self, interaction: discord.Interaction):
        command_name = "/pausedraft"
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active")
            return
        if self.draft_data.get("draft_paused", True): # This logic seems to imply it's already paused
            await interaction.response.send_message("The draft is already paused.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Draft already paused")
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
        guild_config = load_guild_config(interaction.guild.id)
        alerts_channel_id = guild_config.get("alerts_channel")
        alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
        await alerts_channel.send(embed=embed)
        await interaction.response.send_message("Draft paused.", ephemeral=True)
        log_command(interaction, command_name, "Draft paused successfully")
        await self.log_action(interaction, "Draft Paused", "Draft paused")

    @app_commands.command()
    async def resumedraft(self, interaction: discord.Interaction):
        command_name = "/resumedraft"
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active")
            return
        if not self.draft_data.get("draft_paused", False): # This logic implies it's not paused
            await interaction.response.send_message("The draft is not paused.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Draft not paused")
            return

        self.draft_data["draft_paused"] = False
        save_draft(self.draft_data)
        current_team = self.draft_data["draft_order"][
            (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
        ]
        guild_config = load_guild_config(interaction.guild.id)
        team_emojis = guild_config.get("team_emojis", {})
        team_emoji = team_emojis.get(current_team, "")
        embed = discord.Embed(
            title="Draft Resumed",
            description=f"The draft has resumed. {team_emoji} {current_team} is on the clock for Round {self.draft_data['current_round']}, Pick {self.draft_data['current_pick']}.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        alerts_channel_id = guild_config.get("alerts_channel")
        alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
        await alerts_channel.send(embed=embed)
        await interaction.response.send_message("Draft resumed!", ephemeral=True)
        log_command(interaction, command_name, "Draft resumed successfully")
        await self.log_action(interaction, "Draft Resumed", "Draft resumed")

    @app_commands.command()
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager")
    @app_commands.describe(player="The player to draft", team="The team making the pick")
    async def setpick(self, interaction: discord.Interaction, player: discord.Member, team: str):
        guild_config = load_guild_config(interaction.guild.id)
        command_name = "/setpick" # interaction.command.name can be used if it's reliable

        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active", player_id=player.id, player_name=player.display_name, team=team)
            return
        if self.draft_data.get("draft_paused", False):
            await interaction.response.send_message("The draft is paused.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Draft is paused", player_id=player.id, player_name=player.display_name, team=team)
            return
        if team not in guild_config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setup.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Invalid team", player_id=player.id, player_name=player.display_name, team=team)
            return

        team_role_user, team_name_user, _ = self.get_team_info(guild_config, interaction.user) # Renamed
        if team_name_user != team:
            await interaction.response.send_message(f"You can only make picks for your own team.", ephemeral=True)
            log_command(interaction, command_name, "Failed: User cannot pick for this team", player_id=player.id, player_name=player.display_name, team=team, user_team=team_name_user)
            return

        current_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
        if current_index >= len(self.draft_data["draft_order"]):
            await interaction.response.send_message("Draft has ended.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Draft has ended", player_id=player.id, player_name=player.display_name, team=team)
            return
        current_picking_team = self.draft_data["draft_order"][current_index] # Renamed
        if current_picking_team != team:
            await interaction.response.send_message(f"It’s not {team}’s turn to pick.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Not team's turn", player_id=player.id, player_name=player.display_name, team=team, current_turn_team=current_picking_team)
            return

        player_team_role_check, player_team_check, _ = self.get_team_info(guild_config, player) # Renamed
        if player_team_check:
            await interaction.response.send_message(f"{player.display_name} is already on {player_team_check}.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Player already on a team", player_id=player.id, player_name=player.display_name, team=team, player_current_team=player_team_check)
            return

        roster_cap = int(guild_config.get("roster_cap", 53))
        current_roster = len(self.get_team_members(interaction.guild, team))
        if current_roster >= roster_cap:
            await interaction.response.send_message(f"{team} has reached the roster cap ({roster_cap}).", ephemeral=True)
            log_command(interaction, command_name, "Failed: Roster cap reached", player_id=player.id, player_name=player.display_name, team=team, roster_size=current_roster, cap=roster_cap)
            return

        try:
            team_role_obj = discord.utils.get(interaction.guild.roles, name=team) # Renamed
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

            team_emojis = guild_config.get("team_emojis", {})
            team_emoji = team_emojis.get(team, "")
            embed = discord.Embed(
                title="Draft Pick",
                description=f"{team_emoji} {team} selects {player.mention} in Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']}.",
                color=discord.Color.green(), # Changed to green
                timestamp=discord.utils.utcnow()
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            if self.draft_data.get("draft_active", True):
                next_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
                if next_index < len(self.draft_data["draft_order"]):
                    next_team = self.draft_data["draft_order"][next_index]
                    team_emojis = guild_config.get("team_emojis", {})
                    next_emoji = team_emojis.get(next_team, "")
                    embed.add_field(
                        name="Next Pick",
                        value=f"{next_emoji} {next_team} is on the clock for Round {self.draft_data['current_round']}, Pick {self.draft_data['current_pick']}.",
                        inline=False
                    )
            else:
                embed.add_field(name="Draft Complete", value="The draft has concluded!", inline=False)

            alerts_channel_id = guild_config.get("alerts_channel")
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
            await alerts_channel.send(embed=embed)
            await interaction.response.send_message("Pick set!", ephemeral=True)
            await self.log_action(
                interaction,
                "Draft Pick",
                f"{team} picked {player.display_name} (Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']})"
            )
            log_command(interaction, command_name, "Pick set successfully", player_id=player.id, player_name=player.display_name, team=team, round=self.draft_data['picks'][-1]['round'], pick_num=self.draft_data['picks'][-1]['pick'])
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to set pick: {e}", ephemeral=True)
            log_command(interaction, command_name, f"Failed: HTTP Exception - {e}", player_id=player.id, player_name=player.display_name, team=team)

    @app_commands.command()
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager")
    @app_commands.describe(team="The team to toggle autopick for")
    async def autopick(self, interaction: discord.Interaction, team: str):
        guild_config = load_guild_config(interaction.guild.id)
        command_name = "/autopick"

        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active", team=team)
            return
        if team not in guild_config.get("teams", []):
            await interaction.response.send_message("Invalid sending team. Must be created via /setup.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Invalid team", team=team)
            return

        team_role_user, team_name_user, _ = self.get_team_info(guild_config, interaction.user) # Renamed
        if team_name_user != team:
            await interaction.response.send_message("You can only toggle autopick for your own team.", ephemeral=True)
            log_command(interaction, command_name, "Failed: User cannot toggle for this team", team=team, user_team=team_name_user)
            return

        self.draft_data["autopick_settings"][team] = not self.draft_data["autopick_settings"].get(team, False)
        save_draft(self.draft_data)
        new_status_str = "enabled" if self.draft_data["autopick_settings"][team] else "disabled" # Renamed
        team_emojis = guild_config.get("team_emojis", {})
        team_emoji = team_emojis.get(team, "")
        embed = discord.Embed(
            title="Auto-pick Updated",
            description=f"Autopick {status} for {team_emoji} {team}.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log_command(interaction, command_name, f"Autopick {new_status_str} for team", team=team, status=new_status_str)
        await self.log_action(interaction, "Auto-pick Toggled", f"{team} set autopick to {new_status_str}")

    @app_commands.command()
    async def draftorder(self, interaction: discord.Interaction):
        command_name = "/draftorder"
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active")
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
            guild_config = load_guild_config(interaction.guild.id)
            team_emojis = guild_config.get("team_emojis", {})
            for i, team in enumerate(round_picks, 1):
                team_emoji = team_emojis.get(team, "")
                picks.append(f"{team_emoji} {team} (Pick {i})")
            order_by_round.append(f"**Round {round_num}**\n" + "\n".join(picks))

        embed.description = "\n\n".join(order_by_round)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        log_command(interaction, command_name, "Draft order viewed successfully")
        await self.log_action(interaction, "Draft Order Viewed", "Draft order requested")

    @app_commands.command()
    async def draftstatus(self, interaction: discord.Interaction):
        command_name = "/draftstatus"
        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft is currently active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active")
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
            guild_config = load_guild_config(interaction.guild.id)
            team_emojis = guild_config.get("team_emojis", {})
            team_emoji = team_emojis.get(current_team, "")
            embed.add_field(
                name="On the Clock",
                value=f"{team_emoji} {current_team}",
                inline=False
            )

        if self.draft_data["picks"]:
            picks = []
            # guild_config and team_emojis already loaded if current_team was processed
            # otherwise, load them here
            if not current_index < len(self.draft_data["draft_order"]):
                guild_config = load_guild_config(interaction.guild.id)
                team_emojis = guild_config.get("team_emojis", {})
            elif 'team_emojis' not in locals(): # Ensure team_emojis is defined
                guild_config = load_guild_config(interaction.guild.id)
                team_emojis = guild_config.get("team_emojis", {})

            for pick in self.draft_data["picks"]:
                team_emoji = team_emojis.get(pick["team"], "")
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
        log_command(interaction, command_name, "Draft status viewed successfully")
        await self.log_action(interaction, "Draft Status Viewed", "Draft status requested")

    @app_commands.command(name="draftpick", description="Make a draft pick for a team.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(team="The team making the pick", player="The player being drafted")
    @app_commands.autocomplete(team=team_autocomplete)
    async def draftpick(self, interaction: discord.Interaction, team: str, player: discord.Member):
        guild_config = load_guild_config(interaction.guild.id)
        command_name = "/draftpick" # interaction.command.name can be used

        if not self.draft_data.get("draft_active", False):
            await interaction.response.send_message("No draft active.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No draft active", team=team, player_id=player.id, player_name=player.display_name)
            return
        if self.draft_data.get("draft_paused", False):
            await interaction.response.send_message("The draft is paused.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Draft is paused", team=team, player_id=player.id, player_name=player.display_name)
            return
        if team not in guild_config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setup.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Invalid team", team=team, player_id=player.id, player_name=player.display_name)
            return

        # Assuming this command is admin-only, so no check for user's team vs picking team needed like in setpick
        # If that assumption is wrong, add the check and logging here.

        current_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
        if current_index >= len(self.draft_data["draft_order"]):
            await interaction.response.send_message("Draft has ended.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Draft has ended", team=team, player_id=player.id, player_name=player.display_name)
            return
        current_picking_team = self.draft_data["draft_order"][current_index] # Renamed
        if current_picking_team != team:
            await interaction.response.send_message(f"It’s not {team}’s turn to pick.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Not team's turn", team=team, player_id=player.id, player_name=player.display_name, current_turn_team=current_picking_team)
            return

        player_team_role_check, player_team_check, _ = self.get_team_info(guild_config, player) # Renamed
        if player_team_check:
            await interaction.response.send_message(f"{player.display_name} is already on {player_team_check}.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Player already on a team", team=team, player_id=player.id, player_name=player.display_name, player_current_team=player_team_check)
            return

        roster_cap = int(guild_config.get("roster_cap", 53))
        current_roster = len(self.get_team_members(interaction.guild, team))
        if current_roster >= roster_cap:
            await interaction.response.send_message(f"{team} has reached the roster cap ({roster_cap}).", ephemeral=True)
            log_command(interaction, command_name, "Failed: Roster cap reached", team=team, player_id=player.id, player_name=player.display_name, roster_size=current_roster, cap=roster_cap)
            return

        try:
            team_role_obj = discord.utils.get(interaction.guild.roles, name=team) # Renamed
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

            team_emojis = guild_config.get("team_emojis", {})
            team_emoji = team_emojis.get(team, "")
            embed = discord.Embed(
                title="Draft Pick",
                description=f"{team_emoji} {team} selects {player.mention} in Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']}.",
                color=discord.Color.green(), # Changed to green
                timestamp=discord.utils.utcnow()
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            if self.draft_data.get("draft_active", True):
                next_index = (self.draft_data["current_round"] - 1) * self.draft_data["picks_per_round"] + self.draft_data["current_pick"] - 1
                if next_index < len(self.draft_data["draft_order"]):
                    next_team = self.draft_data["draft_order"][next_index]
                    team_emojis = guild_config.get("team_emojis", {})
                    next_emoji = team_emojis.get(next_team, "")
                    embed.add_field(
                        name="Next Pick",
                        value=f"{next_emoji} {next_team} is on the clock for Round {self.draft_data['current_round']}, Pick {self.draft_data['current_pick']}.",
                        inline=False
                    )
            else:
                embed.add_field(name="Draft Complete", value="The draft has concluded!", inline=False)

            alerts_channel_id = guild_config.get("alerts_channel")
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else interaction.channel
            await alerts_channel.send(embed=embed)
            await interaction.response.send_message("Pick set!", ephemeral=True)
            await self.log_action(
                interaction,
                "Draft Pick",
                f"{team} picked {player.display_name} (Round {self.draft_data['picks'][-1]['round']}, Pick {self.draft_data['picks'][-1]['pick']})"
            )
            log_command(interaction, command_name, "Pick set successfully (admin)", player_id=player.id, player_name=player.display_name, team=team, round=self.draft_data['picks'][-1]['round'], pick_num=self.draft_data['picks'][-1]['pick'])
        except discord.errors.HTTPException as e:
            await interaction.response.send_message(f"Failed to set pick: {e}", ephemeral=True)
            log_command(interaction, command_name, f"Failed: HTTP Exception - {e}", player_id=player.id, player_name=player.display_name, team=team)

async def setup(bot):
    await bot.add_cog(DraftCog(bot))