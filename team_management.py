import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime
import asyncio
import pytz

CONFIG_FILE = "config/setup.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

async def team_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    config_file = "config/setup.json"  # Path to the global config
    teams = []
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                content = f.read().strip()
                if content:
                    config_data = json.loads(content)
                    teams = config_data.get("teams", [])
                else:
                    # Config file is empty
                    teams = []
        except json.JSONDecodeError:
            # Config file is malformed
            teams = []
            print(f"Error decoding {config_file}")
        except Exception as e:
            # Other potential errors reading the file
            teams = []
            print(f"Error reading {config_file}: {e}")
    else:
        # Config file does not exist
        teams = []
        print(f"{config_file} not found")

    if not teams: # If teams list is empty for any reason
        return [app_commands.Choice(name="No teams configured. Use /addteam.", value="NO_TEAMS_CONFIGURED_ERROR")]

    choices = [
        app_commands.Choice(name=team_name, value=team_name)
        for team_name in teams if current.lower() in team_name.lower()
    ]
    # Limit to 25 choices as per Discord's limit
    return choices[:25]

class ConfirmModal(discord.ui.Modal):
    def __init__(self, action, callback):
        super().__init__(title=f"Confirm {action}")
        self.callback = callback
        self.add_item(discord.ui.TextInput(
            label="Type 'confirm' to proceed",
            required=True
        ))

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.lower() != "confirm":
            await interaction.response.send_message("Confirmation failed. Action cancelled.", ephemeral=True)
            return
        await self.callback(interaction)

class TeamManagementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()
        self.team_emojis = self.config.get("team_emojis", {})

    def get_guild_config(self, guild_id):
        """Load guild-specific configuration from setup"""
        config_file = f"config/setup_{guild_id}.json"
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        return {}

    def has_admin_roles(self, interaction: discord.Interaction):
        """Check if user has admin or moderator roles"""
        guild_config = self.get_guild_config(interaction.guild.id)
        roles_config = guild_config.get("roles", {})
        
        admin_role_keys = ["admin", "moderator"]
        user_role_ids = [role.id for role in interaction.user.roles]
        
        for role_key in admin_role_keys:
            role_id = roles_config.get(role_key)
            if role_id and role_id in user_role_ids:
                return True
        return False

    def has_franchise_roles(self, interaction: discord.Interaction):
        """Check if user has any of the configured franchise management roles"""
        guild_config = self.get_guild_config(interaction.guild.id)
        roles_config = guild_config.get("roles", {})
        
        franchise_role_keys = ["franchise_owner", "general_manager", "head_coach", "assistant_coach"]
        user_role_ids = [role.id for role in interaction.user.roles]
        
        for role_key in franchise_role_keys:
            role_id = roles_config.get(role_key)
            if role_id and role_id in user_role_ids:
                return True
        return False

    def get_roster_cap(self, guild_id):
        """Get the configured roster cap"""
        guild_config = self.get_guild_config(guild_id)
        return guild_config.get("roster_cap", 53)

    async def log_action(self, guild, action, details, user=None):
        logs_channel_id = self.config.get("logs_channel")
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Team Management: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                if user:
                    embed.set_footer(text=f"Action by {user.display_name}", icon_url=user.avatar.url if user.avatar else None)
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

    # Using shared team_autocomplete from utils.team_utils

    @app_commands.command(name="appoint", description="Appoint a candidate as Franchise Owner of a team.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(candidate="The candidate to appoint", team="The team to assign them to")
    @app_commands.autocomplete(team=team_autocomplete)
    async def appoint(self, interaction: discord.Interaction, candidate: discord.Member, team: str):
        if team not in self.config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /addteam.", ephemeral=True)
            return

        # Load guild-specific setup configuration
        guild_config_file = f"config/setup_{interaction.guild.id}.json"
        guild_config = {}
        if os.path.exists(guild_config_file):
            try:
                with open(guild_config_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        guild_config = json.loads(content)
                    else:
                        guild_config = {}
            except (json.JSONDecodeError, ValueError):
                # File exists but is empty or malformed, use empty config
                guild_config = {}

        # Get roles from setup configuration
        candidate_role_id = guild_config.get("roles", {}).get("candidate")
        fo_role_id = guild_config.get("roles", {}).get("franchise_owner")

        # Debug: Check what's actually in the config
        if not candidate_role_id or not fo_role_id:
            debug_msg = f"Configuration missing roles:\n"
            debug_msg += f"Config file exists: {os.path.exists(guild_config_file)}\n"
            debug_msg += f"Config content: {guild_config}\n"
            debug_msg += f"Candidate role ID: {candidate_role_id}\n"
            debug_msg += f"Franchise Owner role ID: {fo_role_id}"
            print(debug_msg)  # For console debugging

        if not candidate_role_id:
            await interaction.response.send_message("❌ Candidate role not configured. Please run `/setup` and configure the **Candidate** role on page 2, then save the configuration.", ephemeral=True)
            return
        if not fo_role_id:
            await interaction.response.send_message("❌ Franchise Owner role not configured. Please run `/setup` and configure the **Franchise Owner** role on page 1, then save the configuration.", ephemeral=True)
            return

        candidate_role = interaction.guild.get_role(candidate_role_id)
        fo_role = interaction.guild.get_role(fo_role_id)
        team_role = discord.utils.get(interaction.guild.roles, name=team)

        if not candidate_role or not fo_role or not team_role:
            await interaction.response.send_message("Required roles not found or have been deleted.", ephemeral=True)
            return
        if candidate_role not in candidate.roles:
            await interaction.response.send_message(f"{candidate.mention} must have the {candidate_role.mention} role.", ephemeral=True)
            return
        await candidate.remove_roles(candidate_role)
        await candidate.add_roles(fo_role, team_role)

        # Create new embed format
        team_emoji = self.team_emojis.get(team, "")
        embed = discord.Embed(
            title=f"{interaction.guild.name}",
            description="New Appointment",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(
            name="",
            value=f"{candidate.mention} has been appointed as FO of {team_emoji} {team_role.mention}",
            inline=False
        )

        # Set guild icon as thumbnail (left side)
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        # Set team emoji as author icon (top right, full size effect)
        if team_emoji:
            # Try to extract emoji URL if it's a custom emoji
            if team_emoji.startswith('<:') and team_emoji.endswith('>'):
                # Custom emoji format: <:name:id>
                emoji_id = team_emoji.split(':')[-1].rstrip('>')
                emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png"
                embed.set_author(name="", icon_url=emoji_url)

        # Load guild-specific setup configuration for alerts channel
        guild_config_file = f"config/setup_{interaction.guild.id}.json"
        guild_config = {}
        if os.path.exists(guild_config_file):
            try:
                with open(guild_config_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        guild_config = json.loads(content)
                    else:
                        guild_config = {}
            except (json.JSONDecodeError, ValueError):
                guild_config = {}

        # Get alerts channel from guild-specific config
        alerts_channel_id = guild_config.get("channels", {}).get("alerts")
        if alerts_channel_id:
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id))
            if alerts_channel:
                await alerts_channel.send(embed=embed)
            else:
                print(f"Alerts channel not found: {alerts_channel_id}")
        else:
            print("Alerts channel not configured in setup")
        await interaction.response.send_message("FO appointed!", ephemeral=True)
        await self.log_action(interaction.guild, "FO Appointed", f"{candidate.display_name} appointed to {team}", interaction.user)

    # CPU Break: Pause after /appoint
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="appointall", description="Appoint all candidates to teams without an FO.")
    @app_commands.checks.has_permissions(administrator=True)
    async def appointall(self, interaction: discord.Interaction):
        # Load guild-specific setup configuration
        guild_config_file = f"config/setup_{interaction.guild.id}.json"
        guild_config = {}
        if os.path.exists(guild_config_file):
            try:
                with open(guild_config_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        guild_config = json.loads(content)
                    else:
                        guild_config = {}
            except (json.JSONDecodeError, ValueError):
                # File exists but is empty or malformed, use empty config
                guild_config = {}

        # Get roles from setup configuration
        candidate_role_id = guild_config.get("roles", {}).get("candidate")
        fo_role_id = guild_config.get("roles", {}).get("franchise_owner")

        if not candidate_role_id or not fo_role_id:
            await interaction.response.send_message("Required roles not configured. Please run /setup first.", ephemeral=True)
            return

        candidate_role = interaction.guild.get_role(candidate_role_id)
        fo_role = interaction.guild.get_role(fo_role_id)

        if not candidate_role or not fo_role:
            await interaction.response.send_message("Required roles not found or have been deleted.", ephemeral=True)
            return
        candidates = [member for member in interaction.guild.members if candidate_role in member.roles]
        teams = self.config.get("teams", [])
        teams_without_fo = []
        for team in teams:
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            if not team_role:
                continue
            has_fo = any(fo_role in member.roles and team_role in member.roles for member in interaction.guild.members)
            if not has_fo:
                teams_without_fo.append(team)
        # Only appoint up to the number of available teams
        max_appointments = min(len(candidates), len(teams_without_fo))
        if max_appointments == 0:
            await interaction.response.send_message("No candidates or teams available to appoint.", ephemeral=True)
            return

        # Take only the first N candidates where N is the number of teams without FO
        candidates_to_appoint = candidates[:max_appointments]
        teams_to_fill = teams_without_fo[:max_appointments]

        # Create new embed format
        embed = discord.Embed(
            title=f"{interaction.guild.name}",
            description="New Appointments",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        appointment_list = []
        for i, (candidate, team) in enumerate(zip(candidates_to_appoint, teams_to_fill)):
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            if not team_role:
                continue

            await candidate.remove_roles(candidate_role)
            await candidate.add_roles(fo_role, team_role)
            team_emoji = self.team_emojis.get(team, "")
            appointment_list.append(f"{candidate.mention} {team_emoji} {team_role.mention}")
            await self.log_action(interaction.guild, "FO Appointed", f"{candidate.display_name} appointed to {team}", interaction.user)

        # Add all appointments as a single field
        embed.add_field(
            name="",
            value="\n".join(appointment_list),
            inline=False
        )

        # Set guild icon as thumbnail
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        # Get alerts channel from guild-specific config  
        alerts_channel_id = guild_config.get("channels", {}).get("alerts")
        if alerts_channel_id:
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id))
            if alerts_channel:
                await alerts_channel.send(embed=embed)
            else:
                print(f"Alerts channel not found: {alerts_channel_id}")
        else:
            print("Alerts channel not configured in setup")
        await interaction.response.send_message(f"Appointed {max_appointments} candidates!", ephemeral=True)

    # CPU Break: Pause after /appointall
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="waitlist", description="Show the list of candidates waiting for a team.")
    async def waitlist(self, interaction: discord.Interaction):
        # Load guild-specific setup configuration
        guild_config_file = f"config/setup_{interaction.guild.id}.json"
        guild_config = {}
        if os.path.exists(guild_config_file):
            try:
                with open(guild_config_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        guild_config = json.loads(content)
                    else:
                        guild_config = {}
            except (json.JSONDecodeError, ValueError):
                # File exists but is empty or malformed, use empty config
                guild_config = {}

        # Get candidate role from setup configuration
        candidate_role_id = guild_config.get("roles", {}).get("candidate")

        if not candidate_role_id:
            await interaction.response.send_message("Candidate role not configured. Please run /setup first.", ephemeral=True)
            return

        candidate_role = interaction.guild.get_role(candidate_role_id)

        if not candidate_role:
            await interaction.response.send_message("Candidate role not found or has been deleted.", ephemeral=True)
            return
        candidates = [member for member in interaction.guild.members if candidate_role in member.roles]
        embed = discord.Embed(
            title="Candidate Waitlist",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if candidates:
            embed.description = "\n".join(f"{m.mention} ({m.display_name})" for m in candidates)
        else:
            embed.description = "No candidates on the waitlist."
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # CPU Break: Pause after /waitlist
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="franchiselist", description="Show the list of Franchise Owners and their teams.")
    async def franchiselist(self, interaction: discord.Interaction):
        # Load guild-specific setup configuration
        guild_config_file = f"config/setup_{interaction.guild.id}.json"
        guild_config = {}
        if os.path.exists(guild_config_file):
            try:
                with open(guild_config_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        guild_config = json.loads(content)
                    else:
                        guild_config = {}
            except (json.JSONDecodeError, ValueError):
                # File exists but is empty or malformed, use empty config
                guild_config = {}

        # Get franchise owner role from setup configuration
        fo_role_id = guild_config.get("roles", {}).get("franchise_owner")

        if not fo_role_id:
            await interaction.response.send_message("Franchise Owner role not configured. Please run /setup first.", ephemeral=True)
            return

        fo_role = interaction.guild.get_role(fo_role_id)

        if not fo_role:
            await interaction.response.send_message("Franchise Owner role not found or has been deleted.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Franchise Owners",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        roster_cap = int(self.config.get("roster_cap", 53))
        for team in self.config.get("teams", []):
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            if not team_role:
                continue
            fo = next((member for member in interaction.guild.members if fo_role in member.roles and team_role in member.roles), None)
            if not fo:
                continue
            team_members = self.get_team_members(interaction.guild, team)
            team_emoji = self.team_emojis.get(team, "")
            embed.add_field(
                name=f"{team_emoji} {team} ({fo.display_name})",
                value=f"Roster: {len(team_members)}/{roster_cap}",
                inline=False
            )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        owners_channel_id = self.config.get("owners_channel")
        owners_channel = interaction.guild.get_channel(int(owners_channel_id)) if owners_channel_id else None
        if owners_channel:
            await owners_channel.send(embed=embed)
        await interaction.response.send_message("Franchise list sent!", ephemeral=True)
        await self.log_action(interaction.guild, "Franchise List Viewed", "Franchise list requested", interaction.user)

    # CPU Break: Pause after /franchiselist
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="disband", description="Disband a team and remove all roles.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(team="The team to disband")
    @app_commands.autocomplete(team=team_autocomplete)
    async def disband(self, interaction: discord.Interaction, team: str):
        if team not in self.config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setup.", ephemeral=True)
            return
        team_role = discord.utils.get(interaction.guild.roles, name=team)
        if not team_role:
            await interaction.response.send_message("Team role not found.", ephemeral=True)
            return

        async def disband_callback(interaction: discord.Interaction):
            team_emoji = self.team_emojis.get(team, "")
            embed = discord.Embed(
                title=f"{interaction.guild.name} Disbandment Report",
                description=f"Team {team_emoji} {team} has been disbanded.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            staff_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
            staff_info = []
            for staff in staff_roles:
                role = discord.utils.get(interaction.guild.roles, name=staff)
                if not role:
                    continue
                member = next((m for m in interaction.guild.members if role in m.roles and team_role in m.roles), None)
                if member:
                    staff_info.append(f"{staff[:2]}: {member.display_name}")
                    await member.remove_roles(role, team_role)
            players = [m for m in interaction.guild.members if team_role in m.roles]
            for player in players:
                await player.remove_roles(team_role)
            embed.add_field(
                name="Staff Removed",
                value="\n".join(staff_info) or "None",
                inline=False
            )
            embed.add_field(
                name="Players Removed",
                value=", ".join(m.display_name for m in players) or "None",
                inline=False
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            # Load guild-specific setup configuration for alerts channel
            guild_config_file = f"config/setup_{interaction.guild.id}.json"
            guild_config = {}
            if os.path.exists(guild_config_file):
                try:
                    with open(guild_config_file, 'r') as f:
                        content = f.read().strip()
                        if content:
                            guild_config = json.loads(content)
                        else:
                            guild_config = {}
                except (json.JSONDecodeError, ValueError):
                    guild_config = {}

            alerts_channel_id = guild_config.get("channels", {}).get("alerts")
            if alerts_channel_id:
                alerts_channel = interaction.guild.get_channel(int(alerts_channel_id))
                if alerts_channel:
                    await alerts_channel.send(embed=embed)
            await interaction.response.send_message("Team disbanded!", ephemeral=True)
            await self.log_action(interaction.guild, "Team Disbanded", f"Team {team} disbanded", interaction.user)

        modal = ConfirmModal("Disband Team", disband_callback)
        await interaction.response.send_modal(modal)

    # CPU Break: Pause after /disband
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="disbandall", description="Disband all teams.")
    @app_commands.checks.has_permissions(administrator=True)
    async def disbandall(self, interaction: discord.Interaction):
        async def disbandall_callback(interaction: discord.Interaction):
            embed = discord.Embed(
                title=f"{interaction.guild.name} League Disbandment",
                description="All teams have been disbanded.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            staff_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
            for team in self.config.get("teams", []):
                team_role = discord.utils.get(interaction.guild.roles, name=team)
                if not team_role:
                    continue
                team_emoji = self.team_emojis.get(team, "")
                staff_info = []
                for staff in staff_roles:
                    role = discord.utils.get(interaction.guild.roles, name=staff)
                    if not role:
                        continue
                    member = next((m for m in interaction.guild.members if role in m.roles and team_role in m.roles), None)
                    if member:
                        staff_info.append(f"{staff[:2]}: {member.display_name}")
                        await member.remove_roles(role, team_role)
                players = [m for m in interaction.guild.members if team_role in m.roles]
                for player in players:
                    await player.remove_roles(team_role)
                embed.add_field(
                    name=f"{team_emoji} {team}",
                    value=f"Staff: {', '.join(staff_info) or 'None'}\nPlayers: {', '.join(m.display_name for m in players) or 'None'}",
                    inline=False
                )
                await self.log_action(interaction.guild, "Team Disbanded", f"Team {team} disbanded", interaction.user)
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            # Load guild-specific setup configuration for alerts channel
            guild_config_file = f"config/setup_{interaction.guild.id}.json"
            guild_config = {}
            if os.path.exists(guild_config_file):
                try:
                    with open(guild_config_file, 'r') as f:
                        content = f.read().strip()
                        if content:
                            guild_config = json.loads(content)
                        else:
                            guild_config = {}
                except (json.JSONDecodeError, ValueError):
                    guild_config = {}

            alerts_channel_id = guild_config.get("channels", {}).get("alerts")
            if alerts_channel_id:
                alerts_channel = interaction.guild.get_channel(int(alerts_channel_id))
                if alerts_channel:
                    await alerts_channel.send(embed=embed)
            await interaction.response.send_message("All teams disbanded!", ephemeral=True)
            await self.log_action(interaction.guild, "All Teams Disbanded", "All teams disbanded", interaction.user)

        modal = ConfirmModal("Disband All Teams", disbandall_callback)
        await interaction.response.send_modal(modal)

    # CPU Break: Pause after /disbandall
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="roster", description="Show the roster of a team.")
    @app_commands.describe(team="The team to display the roster for")
    @app_commands.autocomplete(team=team_autocomplete)
    async def roster(self, interaction: discord.Interaction, team: str):
        if team not in self.config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setup.", ephemeral=True)
            return
        team_role = discord.utils.get(interaction.guild.roles, name=team)
        if not team_role:
            await interaction.response.send_message("Team role not found.", ephemeral=True)
            return
        team_emoji = self.team_emojis.get(team, "")
        embed = discord.Embed(
            title=f"{team_emoji} {team} Roster",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        staff_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
        for staff in staff_roles:
            role = discord.utils.get(interaction.guild.roles, name=staff)
            if not role:
                continue
            member = next((m for m in interaction.guild.members if role in m.roles and team_role in m.roles), None)
            embed.add_field(
                name=staff,
                value=member.display_name if member else "None",
                inline=True
            )
        players = [m for m in interaction.guild.members if team_role in m.roles and not any(discord.utils.get(m.roles, name=staff) for staff in staff_roles)]
        embed.add_field(
            name="Players",
            value=", ".join(m.display_name for m in players) or "None",
            inline=False
        )
        roster_cap = int(self.config.get("roster_cap", 53))
        embed.add_field(
            name="Roster Cap",
            value=f"{len(self.get_team_members(interaction.guild, team))}/{roster_cap}",
            inline=False
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)
        await self.log_action(interaction.guild, "Roster Viewed", f"Roster for {team} viewed", interaction.user)

    # CPU Break: Pause after /roster
    # asyncio.sleep(2) simulated during code generation

async def setup(bot):
    await bot.add_cog(TeamManagementCog(bot))