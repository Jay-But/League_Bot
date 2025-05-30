import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
from datetime import datetime, timedelta
import pytz
import asyncio
from utils.team_utils import team_autocomplete

DATA_FILE = "league_data.json"
CONFIG_FILE = "config/setup.json"

def load_league_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_league_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

class ScheduleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.league_data = load_league_data()
        self.config = load_config()
        self.check_offseason.start()

    async def log_action(self, guild, action, details):
        logs_channel_id = self.config.get("logs")
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Schedule: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                await logs_channel.send(embed=embed)

    def get_all_teams(self, guild):
        config = load_config()
        return config.get("teams", [])

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="schedule", description="Generate weekly matchups.")
    @app_commands.checks.has_permissions(administrator=True)
    async def schedule(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild_id = str(interaction.guild.id)
        data = self.league_data.get(guild_id, {})
        config = load_config()

        if not data.get("teams"):
            await interaction.followup.send("Use /addteam to select teams.", ephemeral=True)
            return

        if data.get("offseason"):
            resume_date = data.get("resume_date", "unknown")
            await interaction.followup.send(f"League in offseason. Resumes on {resume_date}.", ephemeral=True)
            return

        current_week = data.get("current_week", 1)
        total_weeks = data.get("total_weeks", 18)
        if current_week > total_weeks:
            await interaction.followup.send("Season ended. League is now in offseason.", ephemeral=True)
            return

        teams = data["teams"]
        if len(teams) < 2:
            await interaction.followup.send("Not enough teams to schedule.", ephemeral=True)
            return

        random.shuffle(teams)
        matchups = [(teams[i], teams[i+1]) for i in range(0, len(teams)-1, 2)]
        tz = pytz.timezone("America/Chicago")
        deadline = datetime.now(tz) + timedelta(days=3)
        deadline_str = deadline.strftime("%A, %B %d at 11:59 PM CDT")

        embed = discord.Embed(
            title=f"Week {current_week} Schedule",
            description=f"Games must be completed by {deadline_str}.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        thread_ids = []
        for i, (team1, team2) in enumerate(matchups, 1):
            embed.add_field(
                name=f"Game {i}",
                value=f"{team1} vs {team2}\nDeadline: {deadline_str}",
                inline=False
            )
            try:
                thread = await interaction.channel.create_thread(
                    name=f"{team1} vs {team2} - Week {current_week}",
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=4320
                )
                role1 = discord.utils.get(interaction.guild.roles, name=team1)
                role2 = discord.utils.get(interaction.guild.roles, name=team2)
                mentions = f"{role1.mention if role1 else team1} vs {role2.mention if role2 else team2}"
                await thread.send(f"**Match**: {mentions}\n**Deadline**: {deadline_str}")
                thread_ids.append(thread.id)

                voice_cog = self.bot.get_cog("VoiceChannelManagerCog")
                if voice_cog:
                    category_id = load_config().get("voice_category_id")
                    if category_id:
                        team1_vc, team2_vc = await voice_cog.create_team_voice_channels(
                            interaction.guild, team1, team2, category_id
                        )
                        if team1_vc and team2_vc:
                            voice_cog.team_channels[f"{team1}-{team2}"] = [team1_vc, team2_vc, thread.id]
                            await thread.send(f"Voice Channels:\n{team1}: {team1_vc.mention}\n{team2}: {team2_vc.mention}")
            except Exception as e:
                await interaction.followup.send(f"Error creating thread: {e}", ephemeral=True)
                return

        data["thread_ids"] = thread_ids
        data["current_week"] = current_week + 1
        if data["current_week"] > total_weeks:
            data["offseason"] = True
            resume_date = (datetime.now(tz) + timedelta(days=data.get("offseason_days", 7))).strftime("%Y-%m-%d")
            data["resume_date"] = resume_date
        self.league_data[guild_id] = data
        save_league_data(self.league_data)
        await interaction.followup.send(embed=embed)
        await self.log_action(interaction.guild, "Schedule Generated", f"Week {current_week} scheduled")

    # CPU Break
    # asyncio.sleep(2)

    @tasks.loop(hours=24)
    async def check_offseason(self):
        for guild_id, data in self.league_data.items():
            if isinstance(data, dict) and data.get("offseason"):
                resume_date_str = data.get("resume_date")
                if resume_date_str == resume_date_str:
                    try:
                        resume_date = datetime.strptime(resume_date_str, "%Y-%m-%d")
                        if datetime.utcnow().date() >= resume_date.date():
                            data["offseason"] = False
                            data["current_week"] = 1
                            save_league_data(self.league_data)
                            guild = self.bot.get_guild(int(guild_id))
                            if guild and guild.system_channel:
                                await guild.system_channel.send("League resumed! Week 1 matchups coming soon.")
                                await self.log_action(guild, "Offseason Ended", "League resumed")
                    except ValueError:
                        pass

    @app_commands.command(name="setupteams", description="Add team roles for the league.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupteams(self, interaction: discord.Interaction):
        config = load_config()
        teams = config.get("teams", [])

        class TeamRoleSelect(discord.ui.RoleSelect):
            def __init__(self):
                super().__init__(
                    placeholder="Select team roles",
                    min_values=2,
                    max_values=25
                )

            async def callback(self, interaction: discord.Interaction):
                guild_id = str(interaction.guild.id)
                selected_teams = [v.name for v in self.values]
                config = load_config()
                config["teams"] = selected_teams
                save_config(config)
                await interaction.response.send_message(
                    f"Teams added: {', '.join(selected_teams)}",
                    ephemeral=True
                )
                await self.view.bot.get_cog("ScheduleCog").log_action(
                    interaction.guild,
                    "Teams Added",
                    f"{len(selected_teams)} teams configured"
                )

        class TeamSetupView(discord.ui.View):
            def __init__(self, bot):
                super().__init__()
                self.bot = bot
                self.add_item(TeamRoleSelect())

        await interaction.response.send_message(
            "Select team roles for the league:",
            view=TeamSetupView(self.bot),
            ephemeral=True
        )

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="startplayoffs", description="Start the playoff bracket.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(superbowl_name="Optional name for the Super Bowl")
    async def startplayoffs(self, interaction: discord.Interaction, superbowl_name: str = None):
        guild_id = str(interaction.guild.id)
        config = load_config()
        teams = self.league_data.get(guild_id, {}).get("playoff_teams", config.get("teams", []))
        if not teams or len(teams) < 2:
            await interaction.response.send_message("Need at least 2 teams for playoffs. Please add teams using /addteam and then /addplayoffteams.", ephemeral=True)
            return

        random.shuffle(teams)
        matchups = [(teams[i], teams[i+1]) for i in range(0, len(teams)-1, 2)]
        title = f"{superbowl_name if superbowl_name and len(teams) == 2 else 'Playoff Matches'}"
        embed = discord.Embed(
            title=f"{interaction.guild.name} {title}",
            description="Playoff games scheduled!",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        for i, (team1, team2) in enumerate(matchups, 1):
            embed.add_field(
                name=f"Game {i}",
                value=f"{team1} vs {team2}",
                inline=False
            )
            try:
                thread = await interaction.channel.create_thread(
                    name=f"Playoff {team1} vs {team2}",
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=4320
                )
                role1 = discord.utils.get(interaction.guild.roles, name=team1)
                role2 = discord.utils.get(interaction.guild.roles, name=team2)
                if role1 and role2:
                    await thread.send(f"**Playoff Game**: {role1.mention} vs {role2.mention}")
            except Exception as e:
                await interaction.response.send_message(f"Error creating thread: {e}", ephemeral=True)
                return

        self.league_data[guild_id]["superbowl_name"] = superbowl_name
        save_league_data(self.league_data)
        await interaction.response.send_message(embed=embed)
        await self.log_action(interaction.guild, "Playoffs Started", f"Playoffs with {len(teams)} teams")

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="offseason", description="Start the offseason period.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(days="Number of days for the offseason")
    async def offseason(self, interaction: discord.Interaction, days: int):
        if not 1 <= days <= 90:
            await interaction.response.send_message("Offseason must be 1-90 days.", ephemeral=True)
            return
        guild_id = str(interaction.guild.id)
        if guild_id not in self.league_data:
            await interaction.response.send_message("League not set up. Use /setupteams.", ephemeral=True)
            return

        self.league_data[guild_id]["offseason"] = True
        self.league_data[guild_id]["offseason_days"] = days
        tz = pytz.timezone("America/Chicago")
        resume_date = datetime.now(tz) + timedelta(days=days)
        self.league_data[guild_id]["resume_date"] = resume_date.strftime("%Y-%m-%d")

        embed = discord.Embed(
            title="Offseason Started",
            description=f"League in offseason for {days} days.\nResumes: {resume_date.strftime('%A, %B %d, %Y')}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        schedule_channel_id = self.config.get("schedule")
        if schedule_channel_id:
            schedule_channel = interaction.guild.get_channel(int(schedule_channel_id))
            if schedule_channel:
                await schedule_channel.send(embed=embed)
        save_league_data(self.league_data)
        await interaction.response.send_message("Offseason started!", ephemeral=True)
        await self.log_action(interaction.guild, "Offseason Started", f"Duration: {days} days")

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="gametime", description="Schedule a game with specific date and time.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        team1="First team",
        team2="Second team",
        month="Game month (1-12)",
        day="Game day (1-31)",
        year="Game year",
        hour="Game hour (1-12)",
        minute="Game minute (0-59)",
        ampm="AM or PM"
    )
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete)
    @app_commands.choices(ampm=[
        app_commands.Choice(name="AM", value="AM"),
        app_commands.Choice(name="PM", value="PM")
    ])
    async def gametime(self, interaction: discord.Interaction, team1: str, team2: str, month: int, day: int, year: int, hour: int, minute: int, ampm: str):
        config = load_config()
        teams = config.get("teams", [])
        
        if team1 not in teams or team2 not in teams:
            await interaction.response.send_message("Invalid teams. Must be created via /addteam.", ephemeral=True)
            return
            
        # Validate date/time
        try:
            if month < 1 or month > 12:
                raise ValueError("Invalid month")
            if day < 1 or day > 31:
                raise ValueError("Invalid day") 
            if hour < 1 or hour > 12:
                raise ValueError("Invalid hour")
            if minute < 0 or minute > 59:
                raise ValueError("Invalid minute")
                
            # Convert to 24-hour format
            if ampm == "PM" and hour != 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0
                
            tz = pytz.timezone("America/Chicago")
            game_datetime = tz.localize(datetime(year, month, day, hour, minute))
            current_time = datetime.now(tz)
            
        except ValueError as e:
            await interaction.response.send_message(f"Invalid date/time: {e}", ephemeral=True)
            return

        # Get gametime channel
        gametime_channel_id = config.get("gametime")
        if not gametime_channel_id:
            await interaction.response.send_message("Gametime channel not configured. Please run /setup.", ephemeral=True)
            return
            
        gametime_channel = interaction.guild.get_channel(int(gametime_channel_id))
        if not gametime_channel:
            await interaction.response.send_message("Gametime channel not found.", ephemeral=True)
            return

        # Get team emojis
        team_emojis = config.get("team_emojis", {})
        team1_emoji = team_emojis.get(team1, "")
        team2_emoji = team_emojis.get(team2, "")
        
        # Get team roles
        team1_role = discord.utils.get(interaction.guild.roles, name=team1)
        team2_role = discord.utils.get(interaction.guild.roles, name=team2)
        
        # Calculate time difference
        time_diff = game_datetime - current_time
        if time_diff.total_seconds() > 0:
            hours_until = int(time_diff.total_seconds() // 3600)
            time_status = f"Starts in {hours_until} hours"
        else:
            hours_ago = int(abs(time_diff.total_seconds()) // 3600)
            time_status = f"Started {hours_ago} hours ago"

        embed = discord.Embed(
            title="Game Scheduled",
            description=f"{team1_emoji} {team1_role.mention if team1_role else team1} vs {team2_role.mention if team2_role else team2} {team2_emoji}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        
        if interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        
        embed.add_field(
            name="When",
            value=f"{game_datetime.strftime('%B %d, %Y')} at {game_datetime.strftime('%I:%M %p')} ({time_status})",
            inline=False
        )
        embed.add_field(name="Streamer", value="Click button to assign", inline=True)
        embed.add_field(name="Referee", value="Click button to assign", inline=True)

        class GameTimeView(discord.ui.View):
            def __init__(self, bot, config, team1, team2):
                super().__init__(timeout=None)
                self.bot = bot
                self.config = config
                self.team1 = team1
                self.team2 = team2
                self.streamer = None
                self.referee = None

            @discord.ui.button(label="Streamer", style=discord.ButtonStyle.primary)
            async def streamer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                streamer_role_id = self.config.get("streamer")
                if not streamer_role_id:
                    await interaction.response.send_message("Streamer role not configured in /setup.", ephemeral=True)
                    return
                    
                streamer_role = interaction.guild.get_role(int(streamer_role_id))
                if not streamer_role:
                    await interaction.response.send_message("Streamer role not found.", ephemeral=True)
                    return
                    
                if streamer_role not in interaction.user.roles:
                    await interaction.response.send_message("You don't have the streamer role.", ephemeral=True)
                    return
                    
                self.streamer = interaction.user
                embed = interaction.message.embeds[0]
                embed.set_field_at(1, name="Streamer", value=self.streamer.mention, inline=True)
                await interaction.response.edit_message(embed=embed, view=self)

            @discord.ui.button(label="Referee", style=discord.ButtonStyle.secondary)
            async def referee_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                referee_role_id = self.config.get("referee")
                if not referee_role_id:
                    await interaction.response.send_message("Referee role not configured in /setup.", ephemeral=True)
                    return
                    
                referee_role = interaction.guild.get_role(int(referee_role_id))
                if not referee_role:
                    await interaction.response.send_message("Referee role not found.", ephemeral=True)
                    return
                    
                if referee_role not in interaction.user.roles:
                    await interaction.response.send_message("You don't have the referee role.", ephemeral=True)
                    return
                    
                self.referee = interaction.user
                embed = interaction.message.embeds[0]
                embed.set_field_at(2, name="Referee", value=self.referee.mention, inline=True)
                await interaction.response.edit_message(embed=embed, view=self)

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
            async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message("Only administrators can cancel games.", ephemeral=True)
                    return
                    
                embed = discord.Embed(
                    title="Game Cancelled",
                    description="Sorry, game has been cancelled",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                await interaction.response.edit_message(embed=embed, view=None)

        view = GameTimeView(self.bot, config, team1, team2)
        await gametime_channel.send(embed=embed, view=view)
        await interaction.response.send_message("Game time scheduled successfully!", ephemeral=True)
        await self.log_action(interaction.guild, "Game Time Scheduled", f"{team1} vs {team2}")

    @app_commands.command(name="testschedule", description="Test if the Schedule cog is working.")
    async def testschedule(self, interaction: discord.Interaction):
        await interaction.response.send_message("Schedule cog is operational!", ephemeral=True)

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="addplayoffteams", description="Show all teams registered with /addteam.")
    @app_commands.checks.has_permissions(administrator=True)
    async def addplayoffteams(self, interaction: discord.Interaction):
        # Load team configuration from setup.json
        config = load_config()
        teams = config.get("teams", [])
        team_emojis = config.get("team_emojis", {})

        if not teams:
            await interaction.response.send_message("No teams registered. Use `/addteam` to register teams first.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Registered Teams",
            description=f"All teams registered with `/addteam` (Total: {len(teams)})",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # Add teams to embed with emojis and member counts
        team_list = []
        for team in teams:
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            emoji = team_emojis.get(team, "")

            if team_role:
                member_count = len(team_role.members)
                team_list.append(f"{emoji} **{team}** - {member_count} members")
            else:
                team_list.append(f"{emoji} **{team}** - Role not found")

        # Split teams into chunks if there are too many for one field
        chunk_size = 10
        for i in range(0, len(team_list), chunk_size):
            chunk = team_list[i:i + chunk_size]
            field_name = f"Teams ({i+1}-{min(i+chunk_size, len(team_list))})" if len(team_list) > chunk_size else "Teams"
            embed.add_field(
                name=field_name,
                value="\n".join(chunk),
                inline=False
            )

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.log_action(interaction.guild, "Teams List Viewed", f"Displayed {len(teams)} registered teams")

    @app_commands.command(name="schedulegame", description="Schedule a game between two teams with advanced options.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        team1="First team",
        team2="Second team", 
        deadline="Hours until thread closes",
        autothreads="Auto-create threads for all team matchups",
        autovcs="Auto-create voice channels for teams"
    )
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete)
    @app_commands.choices(
        autothreads=[
            app_commands.Choice(name="Enable", value="enable"),
            app_commands.Choice(name="Disable", value="disable")
        ],
        autovcs=[
            app_commands.Choice(name="Enable", value="enable"),
            app_commands.Choice(name="Disable", value="disable")
        ]
    )
    async def schedulegame(self, interaction: discord.Interaction, team1: str, team2: str, deadline: int = 72, autothreads: str = "disable", autovcs: str = "disable"):
        await interaction.response.defer()
        
        config = load_config()
        teams = config.get("teams", [])
        
        if team1 not in teams or team2 not in teams:
            await interaction.followup.send("Invalid teams. Must be created via /addteam.", ephemeral=True)
            return
            
        if deadline < 1 or deadline > 168:  # 1 hour to 1 week
            await interaction.followup.send("Deadline must be between 1 and 168 hours.", ephemeral=True)
            return

        # Get schedule channel
        schedule_channel_id = config.get("schedule")
        if not schedule_channel_id:
            await interaction.followup.send("Schedule channel not configured. Please run /setup.", ephemeral=True)
            return
            
        schedule_channel = interaction.guild.get_channel(int(schedule_channel_id))
        if not schedule_channel:
            await interaction.followup.send("Schedule channel not found.", ephemeral=True)
            return

        tz = pytz.timezone("America/Chicago")
        current_time = datetime.now(tz)
        deadline_time = current_time + timedelta(hours=deadline)
        
        if autothreads == "enable":
            # Create threads for all team matchups
            if len(teams) < 2:
                await interaction.followup.send("Not enough teams for auto matchups.", ephemeral=True)
                return
                
            random.shuffle(teams)
            matchups = [(teams[i], teams[i+1]) for i in range(0, len(teams)-1, 2)]
            
            embed = discord.Embed(
                title="League Schedule",
                description=f"Auto-generated matchups\nDeadline: {deadline_time.strftime('%A, %B %d at %I:%M %p CDT')}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            for i, (t1, t2) in enumerate(matchups, 1):
                embed.add_field(
                    name=f"Game {i}",
                    value=f"{t1} vs {t2}",
                    inline=False
                )
                
                # Create thread
                thread = await schedule_channel.create_thread(
                    name=f"{t1} vs {t2} - Game {i}",
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=deadline * 60 if deadline <= 72 else 4320
                )
                
                role1 = discord.utils.get(interaction.guild.roles, name=t1)
                role2 = discord.utils.get(interaction.guild.roles, name=t2)
                mentions = f"{role1.mention if role1 else t1} vs {role2.mention if role2 else t2}"
                await thread.send(f"**Match**: {mentions}\n**Deadline**: {deadline_time.strftime('%A, %B %d at %I:%M %p CDT')}")
                
                if autovcs == "enable":
                    voice_cog = self.bot.get_cog("VoiceChannelManagerCog")
                    if voice_cog:
                        category_id = config.get("voice_category_id")
                        if category_id:
                            try:
                                team1_vc, team2_vc = await voice_cog.create_team_voice_channels(
                                    interaction.guild, t1, t2, category_id
                                )
                                if team1_vc and team2_vc:
                                    await thread.send(f"Voice Channels:\n{t1}: {team1_vc.mention}\n{t2}: {team2_vc.mention}")
                            except Exception as e:
                                await thread.send(f"Failed to create voice channels: {e}")
                                
            await schedule_channel.send(embed=embed)
            await interaction.followup.send("Auto-schedule completed!")
            
        else:
            # Create single thread for specified teams
            thread = await schedule_channel.create_thread(
                name=f"{team1} vs {team2}",
                type=discord.ChannelType.public_thread,
                auto_archive_duration=deadline * 60 if deadline <= 72 else 4320
            )
            
            role1 = discord.utils.get(interaction.guild.roles, name=team1)
            role2 = discord.utils.get(interaction.guild.roles, name=team2)
            mentions = f"{role1.mention if role1 else team1} vs {role2.mention if role2 else team2}"
            await thread.send(f"**Match**: {mentions}\n**Deadline**: {deadline_time.strftime('%A, %B %d at %I:%M %p CDT')}")
            
            if autovcs == "enable":
                voice_cog = self.bot.get_cog("VoiceChannelManagerCog")
                if voice_cog:
                    category_id = config.get("voice_category_id")
                    if category_id:
                        try:
                            team1_vc, team2_vc = await voice_cog.create_team_voice_channels(
                                interaction.guild, team1, team2, category_id
                            )
                            if team1_vc and team2_vc:
                                await thread.send(f"Voice Channels:\n{team1}: {team1_vc.mention}\n{team2}: {team2_vc.mention}")
                        except Exception as e:
                            await thread.send(f"Failed to create voice channels: {e}")
            
            embed = discord.Embed(
                title="Game Scheduled",
                description=f"{team1} vs {team2}\nDeadline: {deadline_time.strftime('%A, %B %d at %I:%M %p CDT')}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            await schedule_channel.send(embed=embed)
            await interaction.followup.send("Game scheduled successfully!")
            
        await self.log_action(interaction.guild, "Game Scheduled", f"Teams: {team1} vs {team2}")

    @app_commands.command(name="reschedule", description="Reschedule an existing game.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(home_team="The home team", away_team="The away team", new_date="New game date (YYYY-MM-DD)", new_time="New game time (HH:MM)")
    @app_commands.autocomplete(home_team=team_autocomplete, away_team=team_autocomplete)
    async def reschedule(self, interaction: discord.Interaction, home_team: str, away_team: str, new_date: str, new_time: str):
        await interaction.response.send_message("This command is under development.", ephemeral=True)

    @app_commands.command(name="deletegame", description="Delete a scheduled game.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(home_team="The home team", away_team="The away team")
    @app_commands.autocomplete(home_team=team_autocomplete, away_team=team_autocomplete)
    async def deletegame(self, interaction: discord.Interaction, home_team: str, away_team: str):
        await interaction.response.send_message("This command is under development.", ephemeral=True)

    # CPU Break
    # asyncio.sleep(2)

    def cog_unload(self):
        self.check_offseason.cancel()

async def setup(bot):
    await bot.add_cog(ScheduleCog(bot))