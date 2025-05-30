import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime, timedelta
import pytz
import asyncio
from utils.team_utils import team_autocomplete
from datetime import timezone # Added timezone, datetime is already imported

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
    os.makedirs("config", exist_ok=True)
    config_file = f"config/setup_{str(guild_id)}.json"
    with open(config_file, 'w') as f:
        json.dump(config_data, f, indent=4)

class GameManagementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.config will be loaded per-guild in commands
        # self.team_emojis will be loaded from guild_config per-command

    async def log_action(self, guild, action, details):
        guild_config = load_guild_config(guild.id)
        logs_channel_id = guild_config.get("logs_channel")
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Game Management: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                await logs_channel.send(embed=embed)

    # CPU Break: Pause after cog initialization
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="pickup", description="Host a pickup game.")
    @app_commands.checks.has_any_role("Pickup Host")
    @app_commands.describe(link="The link to the pickup game")
    async def pickup(self, interaction: discord.Interaction, link: str):
        command_name = "/pickup"
        if not link.startswith("http"):
            await interaction.response.send_message("Please provide a valid URL.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Invalid URL provided", link=link)
            return
        embed = discord.Embed(
            title="Pickup Game Announcement",
            description=f"Join the pickup game: [Click Here]({link})\nHosted by {interaction.user.mention}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        guild_config = load_guild_config(interaction.guild.id)
        pickups_channel_id = guild_config.get("pickups_channel")
        pickups_channel = interaction.guild.get_channel(int(pickups_channel_id)) if pickups_channel_id else None
        if pickups_channel:
            await pickups_channel.send(embed=embed)
        await interaction.response.send_message("Pickup game announced!", ephemeral=True)
        log_command(interaction, command_name, "Pickup game announced successfully", link=link)
        # self.log_action is for embed channel logs, distinct from file logs
        await self.log_action(interaction.guild, "Pickup Game", f"Hosted by {interaction.user.display_name}")

    # CPU Break: Pause after /pickup
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="scorereport", description="Report the score of a game.")
    @app_commands.checks.has_any_role("Franchise Owner", "General Manager", "Head Coach", "Assistant Coach")
    @app_commands.describe(
        team1="First team in the matchup",
        team2="Second team in the matchup",
        score_team1="Score for Team 1",
        score_team2="Score for Team 2",
        time="Scheduled game time",
        date="Game date",
        timezone="Timezone for the game",
        channel="Channel to send the report to (optional)",
        thread="Thread to send the report to (optional)"
    )
    @app_commands.choices(time=[
        app_commands.Choice(name=f"{h:02d}:{m:02d} {'PM' if h >= 12 else 'AM'}", value=f"{h:02d}:{m:02d}")
        for h in range(19, 24) for m in [0, 30]
    ])
    @app_commands.choices(date=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="Tomorrow", value="tomorrow"),
        app_commands.Choice(name="2 Days Later", value="2days")
    ])
    @app_commands.choices(timezone=[
        app_commands.Choice(name="EST", value="America/New_York"),
        app_commands.Choice(name="CST", value="America/Chicago"),
        app_commands.Choice(name="PST", value="America/Los_Angeles"),
        app_commands.Choice(name="WST", value="Australia/Perth")
    ])
    async def scorereport(
        self,
        interaction: discord.Interaction,
        team1: str,
        team2: str,
        score_team1: int,
        score_team2: int,
        time: str,
        date: str,
        timezone: str = "America/Chicago",
        channel: str = None,
        thread: str = None
    ):
        guild_config = load_guild_config(interaction.guild.id)
        command_name = "/scorereport"
        log_params = {'team1': team1, 'team2': team2, 'score_team1': score_team1, 'score_team2': score_team2, 'time': time, 'date': date, 'timezone': timezone, 'channel': channel, 'thread': thread}

        if team1 not in guild_config.get("teams", []) or team2 not in guild_config.get("teams", []):
            await interaction.response.send_message("Invalid teams. Must be created via /setup.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Invalid teams", **log_params)
            return
        if score_team1 < 0 or score_team2 < 0:
            await interaction.response.send_message("Scores must be non-negative.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Scores must be non-negative", **log_params)
            return

        tz = pytz.timezone(timezone)
        current_date = datetime.now(tz)
        date_map = {
            "today": current_date,
            "tomorrow": current_date + timedelta(days=1),
            "2days": current_date + timedelta(days=2)
        }
        game_date = date_map.get(date, current_date)
        try:
            game_datetime = game_date.replace(
                hour=int(time.split(":")[0]),
                minute=int(time.split(":")[1]),
                second=0,
                microsecond=0
            )
        except ValueError:
            await interaction.response.send_message("Invalid time format.", ephemeral=True)
            log_command(interaction, command_name, "Failed: Invalid time format", **log_params)
            return

        team1_role = discord.utils.get(interaction.guild.roles, name=team1)
        team2_role = discord.utils.get(interaction.guild.roles, name=team2)
        team_emojis = guild_config.get("team_emojis", {})
        team1_emoji = team_emojis.get(team1, "")
        team2_emoji = team_emojis.get(team2, "")
        formatted_date = game_datetime.strftime("%A, %B %d, %Y")
        embed = discord.Embed(
            title=f"Game Report: {team1_emoji} {team1} vs {team2_emoji} {team2}",
            description=f"**Score**: {team1} {score_team1} - {score_team2} {team2}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(
            name="Scheduled",
            value=f"{formatted_date} at {time} {timezone}",
            inline=False
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        class ScoreReportView(discord.ui.View):
            def __init__(self, user):
                super().__init__(timeout=None)
                self.original_user = user
                self.streamer = None
                self.referee = None

            @discord.ui.button(label="Set Streamer", style=discord.ButtonStyle.primary)
            async def streamer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if "Streamer" not in [role.name for role in interaction.user.roles]:
                    await interaction.response.send_message("You need the Streamer role.", ephemeral=True)
                    return
                self.streamer = interaction.user
                embed.add_field(name="Streamer", value=interaction.user.mention, inline=True)
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("Streamer set!", ephemeral=True)

            @discord.ui.button(label="Set Referee", style=discord.ButtonStyle.green)
            async def referee_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if "Referee" not in [role.name for role in interaction.user.roles]:
                    await interaction.response.send_message("You need the Referee role.", ephemeral=True)
                    return
                self.referee = interaction.user
                embed.add_field(name="Referee", value=interaction.user.mention, inline=True)
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("Referee set!", ephemeral=True)

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
            async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != self.original_user and not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message("Only the original user or admins can cancel.", ephemeral=True)
                    return
                await interaction.message.delete()
                await interaction.response.send_message("Game report cancelled!", ephemeral=True)

        view = ScoreReportView(interaction.user)
        target = None
        if thread:
            target = interaction.guild.get_channel(int(thread)) if thread.isdigit() else None
        elif channel:
            target = interaction.guild.get_channel(int(channel)) if channel.isdigit() else None
        else:
            # guild_config already loaded
            scores_channel_id = guild_config.get("channels", {}).get("scores")
            score_report_channels = [scores_channel_id] if scores_channel_id else []
            if score_report_channels:
                target = interaction.guild.get_channel(int(score_report_channels[0]))
            else:
                await interaction.response.send_message("No score report channel configured. Please specify a channel or thread.", ephemeral=True)
                log_command(interaction, command_name, "Failed: No score report channel configured", **log_params)
                return

        target_id_for_log = target.id if target else "N/A"
        if target:
            await target.send(embed=embed, view=view)
        # Update team records based on scores
        # guild_config already loaded
        if "team_records" not in guild_config:
            guild_config["team_records"] = {}
            
        # Initialize team records if not exists
        for team_name_record in [team1, team2]: # Renamed to avoid conflict
            if team_name_record not in guild_config["team_records"]:
                guild_config["team_records"][team_name_record] = {"wins": 0, "losses": 0}
        
        # Determine winner and update records
        if score_team1 > score_team2:
            guild_config["team_records"][team1]["wins"] += 1
            guild_config["team_records"][team2]["losses"] += 1
            winner = team1
            loser = team2
        elif score_team2 > score_team1:
            guild_config["team_records"][team2]["wins"] += 1
            guild_config["team_records"][team1]["losses"] += 1
            winner = team2
            loser = team1
        else:
            # Tie game - no wins/losses recorded
            winner = None
            loser = None
            
        # Save updated configuration
        save_guild_config(interaction.guild.id, guild_config)

        await interaction.response.send_message("Game report submitted!", ephemeral=True)
        log_command(interaction, command_name, "Game report submitted successfully", **log_params, report_channel_id=target_id_for_log, winner=winner if winner else "Tie/None")
        
        # self.log_action is for embed channel logs
        log_details_embed = f"Reported: {team1} {score_team1} vs {team2} {score_team2}"
        if winner:
            log_details_embed += f" | Winner: {winner}"
        await self.log_action(interaction.guild, "Score Report", log_details_embed)


    # CPU Break: Pause after /scorereport
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="sendscorereport", description="Configure channels or threads for score reports.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channels="Comma-separated list of channel IDs",
        thread="Thread ID"
    )
    async def sendscorereport(self, interaction: discord.Interaction, channels: str = None, thread: str = None):
        guild_config = load_guild_config(interaction.guild.id)
        command_name = "/sendscorereport"
        log_params = {'channels_input': channels, 'thread_input': thread}

        if channels:
            try:
                channel_ids = [int(cid.strip()) for cid in channels.split(",") if cid.strip().isdigit()]
                if not channel_ids:
                    await interaction.response.send_message("No valid channel IDs provided.", ephemeral=True)
                    log_command(interaction, command_name, "Failed: No valid channel IDs provided", **log_params)
                    return

                if "channels" not in guild_config:
                    guild_config["channels"] = {}
                guild_config["channels"]["score_report_channels"] = channel_ids
                save_guild_config(interaction.guild.id, guild_config)
                await interaction.response.send_message(
                    f"Score reports set for channels: {', '.join(f'<#{cid}>' for cid in channel_ids)}",
                    ephemeral=True
                )
                log_command(interaction, command_name, "Score report channels configured successfully", configured_channel_ids=channel_ids)
            except ValueError: # Should not happen with isdigit check, but good for safety
                await interaction.response.send_message("Invalid channel IDs provided.", ephemeral=True)
                log_command(interaction, command_name, "Failed: Invalid character in channel IDs", **log_params)
        elif thread:
            if not thread.isdigit():
                await interaction.response.send_message("Invalid thread ID.", ephemeral=True)
                log_command(interaction, command_name, "Failed: Invalid thread ID (not digit)", **log_params)
                return
            if "channels" not in guild_config:
                guild_config["channels"] = {}
            guild_config["channels"]["score_report_thread"] = int(thread)
            save_guild_config(interaction.guild.id, guild_config)
            await interaction.response.send_message(f"Score reports set for thread: <#{thread}>", ephemeral=True)
            log_command(interaction, command_name, "Score report thread configured successfully", configured_thread_id=thread)
        else:
            await interaction.response.send_message("Please provide channels or a thread ID.", ephemeral=True)
            log_command(interaction, command_name, "Failed: No channels or thread ID provided", **log_params)

        # self.log_action is for embed channel logs
        await self.log_action(interaction.guild, "Score Report Config", f"Channels: {channels}, Thread: {thread}")

    # CPU Break: Pause after /sendscorereport
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="leaderboard", description="Display leaderboards for top players.")
    async def leaderboard(self, interaction: discord.Interaction):
        # Placeholder for stats (no OCR integration)
        stats = {
            "Passer": [],  # QB
            "Receiver": [],  # WR
            "Corner": [],  # DB
            "Defender": []  # DE
        }
        embed = discord.Embed(
            title="Player Leaderboards",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        position_names = {"Passer": "QB", "Receiver": "WR", "Corner": "DB", "Defender": "DE"}
        for position, nickname in position_names.items():
            embed.add_field(
                name=f"{nickname} Leader",
                value="No stats available yet." if not stats[position] else "\n".join(stats[position]),
                inline=False
            )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        guild_config = load_guild_config(interaction.guild.id)
        # Assuming score_report_channels is a list of channels where leaderboards can be posted
        # This was previously configured by sendscorereport.
        # If "scores" is a specific channel for scores, and "score_report_channels" is for reports,
        # this logic might need adjustment based on intended behavior.
        # For now, using "score_report_channels" as set by sendscorereport
        score_report_channel_ids = guild_config.get("channels", {}).get("score_report_channels", [])
        score_report_thread_id = guild_config.get("channels", {}).get("score_report_thread")

        target_channel_ids = score_report_channel_ids
        if score_report_thread_id and score_report_thread_id not in target_channel_ids:
             # Assuming thread is also a valid target for leaderboards
            target_channel_ids.append(score_report_thread_id)

        if not target_channel_ids:
             # Fallback to a "scores" channel if no specific report channels/thread are set
            scores_channel_id = guild_config.get("channels", {}).get("scores")
            if scores_channel_id:
                target_channel_ids.append(scores_channel_id)

        for channel_id in target_channel_ids:
            channel = interaction.guild.get_channel(int(channel_id))
            if channel:
                view = discord.ui.View()
                view.add_item(
                    discord.ui.Button(
                        label="Dismiss",
                        style=discord.ButtonStyle.red,
                        custom_id="dismiss_leaderboard"
                    )
                )
                await channel.send(embed=embed, view=view)
        await interaction.response.send_message("Leaderboard updated!", ephemeral=True)
        log_command(interaction, "/leaderboard", "Player leaderboard displayed successfully")
        # self.log_action is for embed channel logs
        await self.log_action(interaction.guild, "Leaderboard", "Player leaderboard updated")

    # CPU Break: Pause after /leaderboard
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="teamleaderboard", description="Show team win/loss ratios.")
    async def teamleaderboard(self, interaction: discord.Interaction): # This is the first teamleaderboard command
        command_name = "/teamleaderboard" # Differentiating for logs, though it's an overloaded command name
        # Placeholder for team records - this version just displays, doesn't record
        embed = discord.Embed(
            title="Team Leaderboard",
            description="No team records available yet.", # This version might be outdated if the other one works
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        guild_config = load_guild_config(interaction.guild.id)
        # Using the same channel logic as the player leaderboard command
        score_report_channel_ids = guild_config.get("channels", {}).get("score_report_channels", [])
        score_report_thread_id = guild_config.get("channels", {}).get("score_report_thread")

        target_channel_ids = score_report_channel_ids
        if score_report_thread_id and score_report_thread_id not in target_channel_ids:
            target_channel_ids.append(score_report_thread_id)

        if not target_channel_ids:
            scores_channel_id = guild_config.get("channels", {}).get("scores")
            if scores_channel_id:
                target_channel_ids.append(scores_channel_id)

        sent_to_channels = []
        for channel_id in target_channel_ids:
            channel = interaction.guild.get_channel(int(channel_id))
            if channel:
                await channel.send(embed=embed)
                sent_to_channels.append(str(channel.id))

        await interaction.response.send_message("Team leaderboard updated!", ephemeral=True)
        log_command(interaction, command_name, "Team leaderboard (display only) shown", sent_to_channel_ids=sent_to_channels if sent_to_channels else "None")
        # self.log_action is for embed channel logs
        await self.log_action(interaction.guild, "Team Leaderboard", "Team leaderboard (display only) updated")


    @app_commands.command(name="teamscore", description="Record a score for a team.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(home_team="The home team", away_team="The away team", home_score="Home team score", away_score="Away team score")
    @app_commands.autocomplete(home_team=team_autocomplete, away_team=team_autocomplete)
    async def teamscore(self, interaction: discord.Interaction, home_team: str, away_team: str, home_score: int, away_score: int):
        log_command(interaction, "/teamscore", "Attempted: Command not implemented", home_team=home_team, away_team=away_team, home_score=home_score, away_score=away_score)
        pass

    @app_commands.command(name="teamstats", description="Show statistics for a team.")
    @app_commands.describe(team="The team to show stats for")
    @app_commands.autocomplete(team=team_autocomplete)
    async def teamstats(self, interaction: discord.Interaction, team: str):
        log_command(interaction, "/teamstats", "Attempted: Command not implemented", team=team)
        pass

    @app_commands.command(name="teamleaderboard", description="Show team win/loss leaderboard and record scores.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(winning_team="The team that won (optional)", losing_team="The team that lost (optional)")
    @app_commands.autocomplete(winning_team=team_autocomplete, losing_team=team_autocomplete)
    async def teamleaderboard(self, interaction: discord.Interaction, winning_team: str = None, losing_team: str = None): # This is the second teamleaderboard command
        guild_config = load_guild_config(interaction.guild.id)
        command_name = "/teamleaderboard" # Same command name, but logic differs
        log_params = {'winning_team_input': winning_team, 'losing_team_input': losing_team}

        teams = guild_config.get("teams", [])
        
        if not teams:
            await interaction.response.send_message("No teams found. Please add teams using /setupteams.", ephemeral=True) # Corrected to /setupteams
            log_command(interaction, command_name, "Failed: No teams found", **log_params)
            return

        score_recorded_message = ""
        # If both teams provided, record the win/loss
        if winning_team and losing_team:
            if winning_team not in teams or losing_team not in teams:
                await interaction.response.send_message("Invalid teams. Must be created via /setupteams.", ephemeral=True) # Corrected
                log_command(interaction, command_name, "Failed: Invalid winning or losing team", **log_params)
                return
            if winning_team == losing_team:
                await interaction.response.send_message("Winning and losing team cannot be the same.", ephemeral=True)
                log_command(interaction, command_name, "Failed: Winning and losing team cannot be the same", **log_params)
                return
                
            # Initialize team records if not exists
            if "team_records" not in guild_config:
                guild_config["team_records"] = {}
                
            for team in teams:
                if team not in guild_config["team_records"]:
                    guild_config["team_records"][team] = {"wins": 0, "losses": 0}
            
            # Update records
            guild_config["team_records"][winning_team]["wins"] += 1
            guild_config["team_records"][losing_team]["losses"] += 1
            
            # Save configuration
            save_guild_config(interaction.guild.id, guild_config)
                
            await interaction.response.send_message(f"✅ Recorded: {winning_team} defeated {losing_team}", ephemeral=True)
            
        # Show leaderboard
        team_records = guild_config.get("team_records", {})
        
        # Initialize any missing teams
        for team in teams:
            if team not in team_records:
                team_records[team] = {"wins": 0, "losses": 0}
        
        # Sort teams by wins (descending), then by losses (ascending)
        sorted_teams = sorted(teams, key=lambda t: (team_records[t]["wins"], -team_records[t]["losses"]), reverse=True)
        
        embed = discord.Embed(
            title="📊 Team Leaderboard",
            description="Win/Loss records for all teams",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        leaderboard_text = []
        for i, team in enumerate(sorted_teams, 1):
            wins = team_records[team]["wins"]
            losses = team_records[team]["losses"]
            total_games = wins + losses
            win_rate = (wins / total_games * 100) if total_games > 0 else 0
            
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            team_emojis = guild_config.get("team_emojis", {})
            team_emoji = team_emojis.get(team, "")
            
            leaderboard_text.append(
                f"**{i}.** {team_emoji} {team}\n"
                f"   Record: {wins}-{losses} ({win_rate:.1f}%)"
            )
        
        # Split into chunks to avoid embed limit
        chunk_size = 10
        for i in range(0, len(leaderboard_text), chunk_size):
            chunk = leaderboard_text[i:i + chunk_size]
            field_name = f"Rankings ({i+1}-{min(i+chunk_size, len(leaderboard_text))})" if len(leaderboard_text) > chunk_size else "Rankings"
            embed.add_field(
                name=field_name,
                value="\n\n".join(chunk),
                inline=False
            )
        
        embed.set_footer(text="Use /teamleaderboard <winning_team> <losing_team> to record a game result")
        
        if winning_team and losing_team: # A score was recorded
            # The ephemeral message about recording is sent before this,
            # so we edit the original response which would have been the leaderboard.
            # If interaction.response.is_done() is false, it implies the ephemeral message was it.
            # This part of the logic for ephemeral vs followup might need review based on how it behaves.
            # For now, assuming edit_original_response is for an existing leaderboard message if one was sent.
            # However, the ephemeral "Recorded" message is likely the first response.
            # If so, a new message or followup should be used for the leaderboard itself.
            # Let's assume the ephemeral "Recorded" is fine and we send a new message for the leaderboard if scores were input.
            # await interaction.edit_original_response(embed=embed)
            await interaction.followup.send(embed=embed, ephemeral=False) # Send leaderboard as a new message
            score_recorded_message = f"Recorded score ({winning_team} def. {losing_team}) and "
        else: # Just displaying leaderboard
            await interaction.response.send_message(embed=embed)

        log_outcome_message = f"{score_recorded_message}Displayed team leaderboard."
        final_log_params = {'winning_team': winning_team, 'losing_team': losing_team} if (winning_team and losing_team) else {}
        log_command(interaction, command_name, log_outcome_message, **final_log_params)
            
        # self.log_action is for embed channel logs
        await self.log_action(interaction.guild, "Leaderboard Viewed", f"Teams: {len(teams)}")


    # CPU Break: Pause after /teamleaderboard
    # asyncio.sleep(2) simulated during code generation

async def setup(bot):
    await bot.add_cog(GameManagementCog(bot))