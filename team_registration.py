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

class TeamRegistrationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.config removed

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
        return interaction.user.guild_permissions.administrator

    async def log_action(self, guild, action, details, user=None):
        # Use guild logger for comprehensive logging
        guild_logger = get_guild_logger(self.bot)
        await guild_logger.log_action(guild, f"Team Registration: {action}", details, user)

    @app_commands.command(name="addteam", description="Register a role as a team with an associated emoji.")
    async def addteam(self, interaction: discord.Interaction):
        # Check if user has required roles from setup
        if not self.has_admin_roles(interaction):
            await interaction.response.send_message("❌ You don't have permission to add teams. Please contact an administrator to configure roles via `/setup`.", ephemeral=True)
            return

        # Get all custom emojis in the guild
        emojis = interaction.guild.emojis
            
        if not emojis:
            await interaction.response.send_message("No custom emojis available in this guild.", ephemeral=True)
            return

        class RoleSelectButton(discord.ui.RoleSelect):
            def __init__(self):
                super().__init__(
                    placeholder="Choose a role to register as a team",
                    min_values=1,
                    max_values=1
                )

            async def callback(self, interaction: discord.Interaction):
                selected_role = self.values[0]
                
                self.view.selected_role = selected_role
                self.view.role_selected = True
                
                # Update the view to show emoji selection
                self.view.clear_items()
                self.view.add_item(EmojiSelect())
                
                embed = discord.Embed(
                    title="Team Registration",
                    description=f"Selected Role: **{selected_role.name}**\nNow select an emoji:",
                    color=discord.Color.blue()
                )
                
                await interaction.response.edit_message(embed=embed, view=self.view)

        class EmojiSelect(discord.ui.Select):
            def __init__(self):
                options = [
                    discord.SelectOption(
                        label=emoji.name,
                        value=str(emoji.id),
                        emoji=emoji
                    ) for emoji in emojis[:25]  # Discord limit of 25 options
                ]
                super().__init__(placeholder="Choose an emoji for the team", options=options)

            async def callback(self, interaction: discord.Interaction):
                selected_emoji_id = int(self.values[0])
                selected_emoji = discord.utils.get(interaction.guild.emojis, id=selected_emoji_id)
                
                if not selected_emoji:
                    await interaction.response.send_message("Selected emoji not found.", ephemeral=True)
                    return
                
                # Register the team
                role = self.view.selected_role
                # cog = interaction.client.get_cog("TeamRegistrationCog") # Not needed for config access

                # Load, update, and save guild-specific config
                guild_id = interaction.guild.id
                guild_config = load_guild_config(guild_id)
                
                if "teams" not in guild_config:
                    guild_config["teams"] = []
                if "team_emojis" not in guild_config:
                    guild_config["team_emojis"] = {}
                
                # Add team if not already registered
                if role.name not in guild_config["teams"]:
                    guild_config["teams"].append(role.name)
                
                # Add/update emoji mapping
                guild_config["team_emojis"][role.name] = str(selected_emoji)
                
                save_guild_config(guild_id, guild_config)
                
                # Create success embed
                embed = discord.Embed(
                    title="Team Registered Successfully!",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                
                embed.add_field(
                    name="Team Details",
                    value=f"**Role:** {role.mention}\n**Emoji:** {selected_emoji}\n**Members:** {len(role.members)}",
                    inline=False
                )
                
                if interaction.guild.icon:
                    embed.set_thumbnail(url=interaction.guild.icon.url)
                
                await interaction.response.edit_message(embed=embed, view=None)
                
                # Log the action
                await cog.log_action(
                    interaction.guild,
                    "Team Registered",
                    f"Role: {role.name}, Emoji: {selected_emoji.name}, Members: {len(role.members)}",
                    interaction.user
                )
                
                # Comprehensive logging
                comp_logger = get_comprehensive_logger(interaction.client)
                await comp_logger.log_team_creation(
                    interaction.guild,
                    role.name,
                    interaction.user,
                    selected_emoji
                )

        class TeamRegistrationView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)  # 5 minutes timeout
                self.selected_role = None
                self.role_selected = False
                self.add_item(RoleSelectButton())

            async def on_timeout(self):
                for item in self.children:
                    item.disabled = True

        embed = discord.Embed(
            title="Team Registration",
            description="Select a role to register as a team:",
            color=discord.Color.blue()
        )
        
        view = TeamRegistrationView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="listteams", description="List all registered teams.")
    async def listteams(self, interaction: discord.Interaction):
        guild_config = load_guild_config(interaction.guild.id) # Load guild_config
        teams = guild_config.get("teams", [])
        team_emojis = guild_config.get("team_emojis", {})
        
        if not teams:
            await interaction.response.send_message("No teams registered.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Registered Teams",
            description=f"Total teams: {len(teams)}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        for team in teams:
            role = discord.utils.get(interaction.guild.roles, name=team)
            emoji = team_emojis.get(team, "")
            
            if role:
                embed.add_field(
                    name=f"{emoji} {team}",
                    value=f"Role: {role.mention}\nMembers: {len(role.members)}",
                    inline=True
                )
            else:
                embed.add_field(
                    name=f"{emoji} {team}",
                    value="Role not found",
                    inline=True
                )
        
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(TeamRegistrationCog(bot))
