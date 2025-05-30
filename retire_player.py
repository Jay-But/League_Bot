import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime
import pytz
import asyncio

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

class RetirePlayerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.config and self.team_emojis removed

    def get_guild_config(self, guild_id):
        return load_guild_config(guild_id)

    def has_required_roles(self, interaction: discord.Interaction):
        """Check if user has any of the configured franchise management roles"""
        guild_config = self.get_guild_config(interaction.guild.id)
        roles_config = guild_config.get("roles", {})
        
        required_role_keys = ["franchise_owner", "general_manager", "head_coach", "assistant_coach"]
        user_role_ids = [role.id for role in interaction.user.roles]
        
        for role_key in required_role_keys:
            role_id = roles_config.get(role_key)
            if role_id and role_id in user_role_ids:
                return True
        return False

    def get_logs_channel(self, guild):
        """Get the configured logs channel"""
        guild_config = self.get_guild_config(guild.id)
        channels_config = guild_config.get("channels", {})
        logs_channel_id = channels_config.get("logs")
        
        if logs_channel_id:
            return guild.get_channel(logs_channel_id)
        return None

    async def log_action(self, guild, action, details):
        logs_channel = self.get_logs_channel(guild)
        if logs_channel:
            embed = discord.Embed(
                title=f"Retirement: {action}",
                description=details,
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await logs_channel.send(embed=embed)

    def get_team_info(self, member: discord.Member): # Added type hint
        guild_config = load_guild_config(member.guild.id) # Use new helper
        team_emojis = guild_config.get("team_emojis", {})
        teams = guild_config.get("teams", [])
        for role in member.roles:
            if role.name in teams and role.name != "@everyone":
                emoji = team_emojis.get(role.name, "")
                return role, role.name, emoji
        return None, None, "" # Consistent return

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="retire", description="Retire a player from your team.")
    @app_commands.checks.has_any_role("Franchise Owner")
    @app_commands.describe(player="The player to retire", message="Optional retirement message")
    async def retire(self, interaction: discord.Interaction, player: discord.Member, message: str = None):
        guild_config = load_guild_config(interaction.guild.id) # Load guild_config
        team_role, team_name, team_emoji = self.get_team_info(interaction.user)
        if not team_role:
            await interaction.response.send_message("You are not part of a valid team.", ephemeral=True)
            return
        if team_role not in player.roles:
            await interaction.response.send_message(f"{player.mention} is not on your team.", ephemeral=True)
            return

        try:
            await player.remove_roles(team_role)
        except discord.Forbidden:
            await interaction.response.send_message("I lack permission to manage roles.", ephemeral=True)
            return

        hof_role = None
        hof_id = guild_config.get("hof_role_id") # Use guild_config
        if hof_id:
            hof_role = discord.utils.get(interaction.guild.roles, id=int(hof_id))
            if hof_role:
                try:
                    await player.add_roles(hof_role)
                except:
                    pass

        embed = discord.Embed(
            title=f"{player.display_name} Retires",
            description=f"{player.mention} has retired from {team_emoji} {team_name}.",
            color=discord.Color.dark_gold(),
            timestamp=discord.utils.utcnow()
        )
        if message:
            embed.add_field(name="Retirement Message", value=message, inline=False)
        if hof_role:
            embed.add_field(name="Hall of Fame", value=f"{player.mention} inducted into {hof_role.mention}!")
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.response.send_message(embed=embed)

        # log_action will fetch the logs_channel from guild_config
        await self.log_action(
            interaction.guild,
            "Player Retired",
            f"{player.display_name} retired from {team_name}"
        )

        # Send to transactions channel from guild-specific setup
        # guild_config already loaded
        transactions_channel_id = guild_config.get("channels", {}).get("transactions")
        if transactions_channel_id:
            transactions_channel = interaction.guild.get_channel(int(transactions_channel_id))
            if transactions_channel:
                await transactions_channel.send(embed=embed)

    # CPU Break: Pause after /retire
    # asyncio.sleep(2) simulated during code generation

async def setup(bot):
    await bot.add_cog(RetirePlayerCog(bot))