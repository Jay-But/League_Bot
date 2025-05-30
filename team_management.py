import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime
import pytz
import asyncio
from utils.team_utils import team_autocomplete

# CONFIG_FILE, load_config, save_config removed

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
        # self.config and self.team_emojis removed

    def get_guild_config(self, guild_id):
        return load_guild_config(guild_id) # Use the standalone helper

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
        guild_config = load_guild_config(guild.id) # Load guild_config
        logs_channel_id = guild_config.get("logs_channel") # Get from guild_config
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
        guild_config = load_guild_config(member.guild.id) # Load guild_config
        teams = guild_config.get("teams", [])
        team_emojis = guild_config.get("team_emojis", {})
        for role in member.roles:
            if role.name in teams and role.name != "@everyone":
                emoji = team_emojis.get(role.name, "")
                return role, role.name, emoji
        return None, None, None # Ensure consistent return for no team found

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
        guild_config = load_guild_config(interaction.guild.id) # Use helper

        if team not in guild_config.get("teams", []): # Use guild_config
            await interaction.response.send_message("Invalid team. Must be created via /setupteams.", ephemeral=True) # Changed to /setupteams
            return

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
            # print(debug_msg) # Keep for local debugging if necessary, but remove for production
            pass # Assuming this debug code is not needed for the refactor itself

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
        team_emojis_local = guild_config.get("team_emojis", {}) # Load from guild_config
        team_emoji = team_emojis_local.get(team, "")
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

        # guild_config already loaded earlier
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
        guild_config = load_guild_config(interaction.guild.id) # Use helper

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
        teams_list = guild_config.get("teams", []) # Use guild_config
        teams_without_fo = []
        for team in teams_list: # Iterate over teams_list
            team_role = discord.utils.get(interaction.guild.roles, name=team)
            if not team_role:
                continue
            has_fo = any(fo_role in member.roles and team_role in member.roles for member in interaction.guild.members)
            if not has_fo:
                teams_without_fo.append(team) # team is a string name
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
            team_role_obj = discord.utils.get(interaction.guild.roles, name=team_name_appoint) # Renamed
            if not team_role_obj:
                continue

            await candidate.remove_roles(candidate_role)
            await candidate.add_roles(fo_role, team_role_obj)
            team_emojis_local = guild_config.get("team_emojis", {}) # Load from guild_config
            team_emoji = team_emojis_local.get(team_name_appoint, "")
            appointment_list.append(f"{candidate.mention} {team_emoji} {team_role_obj.mention}")
            await self.log_action(interaction.guild, "FO Appointed", f"{candidate.display_name} appointed to {team_name_appoint}", interaction.user)

        # Add all appointments as a single field
        embed.add_field(
            name="",
            value="\n".join(appointment_list),
            inline=False
        )

        # Set guild icon as thumbnail
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        # guild_config already loaded
        alerts_channel_id = guild_config.get("channels", {}).get("alerts")
        if alerts_channel_id:
            alerts_channel = interaction.guild.get_channel(int(alerts_channel_id))
            if alerts_channel:
                await alerts_channel.send(embed=embed)
            else:
                # print(f"Alerts channel not found: {alerts_channel_id}") # Keep for local debug
                pass
        else:
            # print("Alerts channel not configured in setup") # Keep for local debug
            pass
        await interaction.response.send_message(f"Appointed {max_appointments} candidates!", ephemeral=True)

    # CPU Break: Pause after /appointall
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="waitlist", description="Show the list of candidates waiting for a team.")
    async def waitlist(self, interaction: discord.Interaction):
        guild_config = load_guild_config(interaction.guild.id) # Use helper

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
        guild_config = load_guild_config(interaction.guild.id) # Use helper

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
        roster_cap = int(guild_config.get("roster_cap", 53)) # Use guild_config
        teams_list = guild_config.get("teams", []) # Use guild_config
        team_emojis_local = guild_config.get("team_emojis", {}) # Use guild_config

        for team_name_list in teams_list: # Renamed
            team_role = discord.utils.get(interaction.guild.roles, name=team_name_list)
            if not team_role:
                continue
            fo = next((member for member in interaction.guild.members if fo_role in member.roles and team_role in member.roles), None)
            if not fo:
                continue # Skip if no FO for this team_role
            team_members = self.get_team_members(interaction.guild, team_name_list)
            team_emoji = team_emojis_local.get(team_name_list, "")
            embed.add_field(
                name=f"{team_emoji} {team_name_list} ({fo.display_name})",
                value=f"Roster: {len(team_members)}/{roster_cap}",
                inline=False
            )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        owners_channel_id = guild_config.get("channels", {}).get("owners") # Use guild_config, assuming 'owners' is under 'channels'
        owners_channel = interaction.guild.get_channel(int(owners_channel_id)) if owners_channel_id else None
        if owners_channel:
            await owners_channel.send(embed=embed)
        else:
            # If owners_channel is not configured or found, send to current channel or as response
            await interaction.response.send_message(embed=embed, ephemeral=True) # Send as response if channel missing
            # Log that owners channel was not found/configured if necessary
            return # Avoid sending "Franchise list sent!" if already sent as response

        await interaction.response.send_message("Franchise list sent to owners channel!", ephemeral=True)
        await self.log_action(interaction.guild, "Franchise List Viewed", "Franchise list requested", interaction.user)

    # CPU Break: Pause after /franchiselist
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="disband", description="Disband a team and remove all roles.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(team="The team to disband")
    @app_commands.autocomplete(team=team_autocomplete)
    async def disband(self, interaction: discord.Interaction, team: str):
        guild_config_main = load_guild_config(interaction.guild.id) # Load for initial check

        if team not in guild_config_main.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setupteams.", ephemeral=True) # Changed to /setupteams
            return
        team_role = discord.utils.get(interaction.guild.roles, name=team)
        if not team_role:
            await interaction.response.send_message("Team role not found.", ephemeral=True)
            return

        async def disband_callback(interaction_cb: discord.Interaction): # Renamed interaction
            # Reload guild_config inside callback for fresh data if needed, though for emojis it might not change often
            guild_config_cb = load_guild_config(interaction_cb.guild.id)
            team_emojis_cb = guild_config_cb.get("team_emojis", {})
            team_emoji = team_emojis_cb.get(team, "")
            embed = discord.Embed(
                title=f"{interaction_cb.guild.name} Disbandment Report",
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
            if interaction_cb.guild.icon: # Use interaction_cb
                embed.set_thumbnail(url=interaction_cb.guild.icon.url)

            # guild_config_cb already loaded for emojis
            alerts_channel_id = guild_config_cb.get("channels", {}).get("alerts")
            if alerts_channel_id:
                alerts_channel = interaction_cb.guild.get_channel(int(alerts_channel_id)) # Use interaction_cb
                if alerts_channel:
                    await alerts_channel.send(embed=embed)
            await interaction_cb.response.send_message("Team disbanded!", ephemeral=True) # Use interaction_cb
            await self.log_action(interaction_cb.guild, "Team Disbanded", f"Team {team} disbanded", interaction_cb.user) # Use interaction_cb

        modal = ConfirmModal("Disband Team", disband_callback)
        await interaction.response.send_modal(modal)

    # CPU Break: Pause after /disband
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="disbandall", description="Disband all teams.")
    @app_commands.checks.has_permissions(administrator=True)
    async def disbandall(self, interaction: discord.Interaction):
        async def disbandall_callback(interaction_cb: discord.Interaction): # Renamed interaction
            guild_config_cb = load_guild_config(interaction_cb.guild.id) # Load guild_config in callback
            embed = discord.Embed(
                title=f"{interaction_cb.guild.name} League Disbandment",
                description="All teams have been disbanded.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            staff_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"] # Consider making these configurable
            teams_cb = guild_config_cb.get("teams", [])
            team_emojis_cb = guild_config_cb.get("team_emojis", {})

            for team_name_cb in teams_cb: # Iterate over teams from guild_config
                team_role = discord.utils.get(interaction_cb.guild.roles, name=team_name_cb)
                if not team_role:
                    continue
                team_emoji = team_emojis_cb.get(team_name_cb, "")
                staff_info = []
                for staff in staff_roles: # staff is a string role name
                    role = discord.utils.get(interaction_cb.guild.roles, name=staff)
                    if not role: # Role name from staff_roles might not exist
                        continue
                    # Ensure member is part of the current team_role being processed
                    member = next((m for m in interaction_cb.guild.members if role in m.roles and team_role in m.roles), None)
                    if member:
                        staff_info.append(f"{staff[:2]}: {member.display_name}") # Using original staff name for display
                        await member.remove_roles(role, team_role)
                players = [m for m in interaction_cb.guild.members if team_role in m.roles and not any(discord.utils.get(m.roles, name=s_role) for s_role in staff_roles)] # Exclude staff from players
                for player in players:
                    await player.remove_roles(team_role)
                embed.add_field(
                    name=f"{team_emoji} {team_name_cb}",
                    value=f"Staff: {', '.join(staff_info) or 'None'}\nPlayers: {', '.join(p.display_name for p in players) or 'None'}", # Use p.display_name
                    inline=False
                )
                await self.log_action(interaction_cb.guild, "Team Disbanded", f"Team {team_name_cb} disbanded", interaction_cb.user)
            if interaction_cb.guild.icon:
                embed.set_thumbnail(url=interaction_cb.guild.icon.url)

            # guild_config_cb already loaded
            alerts_channel_id = guild_config_cb.get("channels", {}).get("alerts")
            if alerts_channel_id:
                alerts_channel = interaction_cb.guild.get_channel(int(alerts_channel_id))
                if alerts_channel:
                    await alerts_channel.send(embed=embed)
            await interaction_cb.response.send_message("All teams disbanded!", ephemeral=True)
            await self.log_action(interaction_cb.guild, "All Teams Disbanded", "All teams disbanded", interaction_cb.user)

        modal = ConfirmModal("Disband All Teams", disbandall_callback)
        await interaction.response.send_modal(modal)

    # CPU Break: Pause after /disbandall
    # asyncio.sleep(2) simulated during code generation

    @app_commands.command(name="roster", description="Show the roster of a team.")
    @app_commands.describe(team="The team to display the roster for")
    @app_commands.autocomplete(team=team_autocomplete)
    async def roster(self, interaction: discord.Interaction, team: str):
        guild_config = load_guild_config(interaction.guild.id) # Load guild_config

        if team not in guild_config.get("teams", []):
            await interaction.response.send_message("Invalid team. Must be created via /setupteams.", ephemeral=True) # Changed to /setupteams
            return
        team_role = discord.utils.get(interaction.guild.roles, name=team)
        if not team_role:
            await interaction.response.send_message("Team role not found.", ephemeral=True)
            return

        team_emojis_local = guild_config.get("team_emojis", {}) # Load from guild_config
        team_emoji = team_emojis_local.get(team, "")
        embed = discord.Embed(
            title=f"{team_emoji} {team} Roster",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        # Consider making staff_roles configurable if they vary per guild
        staff_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
        for staff_role_name in staff_roles: # Renamed
            # Role IDs for staff should ideally be fetched from guild_config if they are configurable
            # For now, assuming role names are fixed as per original code
            role = discord.utils.get(interaction.guild.roles, name=staff_role_name)
            if not role:
                continue
            member = next((m for m in interaction.guild.members if role in m.roles and team_role in m.roles), None)
            embed.add_field(
                name=staff_role_name,
                value=member.display_name if member else "None",
                inline=True
            )

        players = [m for m in interaction.guild.members if team_role in m.roles and not any(discord.utils.get(m.roles, name=s_role) for s_role in staff_roles)]
        embed.add_field(
            name="Players",
            value=", ".join(p.display_name for p in players) or "None", # Use p.display_name
            inline=False
        )
        roster_cap = int(guild_config.get("roster_cap", 53)) # Load from guild_config
        embed.add_field(
            name="Roster Cap",
            value=f"{len(self.get_team_members(interaction.guild, team))}/{roster_cap}", # get_team_members is fine
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