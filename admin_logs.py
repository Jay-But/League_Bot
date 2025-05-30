import discord
from discord import app_commands
from discord.ext import commands
import json
from utils.comprehensive_logger import get_comprehensive_logger
import os # Added
from datetime import datetime, timezone # Added
# discord is already imported via `import discord` from line 1

LOG_DIR = "guild_logs"

def ensure_log_dir():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

def format_log_message(user: discord.User | discord.Member, command_name: str, outcome: str, details: dict) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    user_info = f"{user.name}#{user.discriminator} ({user.id})"
    # Truncate command_name if it starts with / to avoid //
    if command_name.startswith('/'):
        display_command_name = command_name
    else:
        display_command_name = f"/{command_name}"

    details_str_parts = []
    for k, v in details.items():
        # Truncate long string values in details
        if isinstance(v, str) and len(v) > 75:
            details_str_parts.append(f"{k}={v[:75]}...")
        else:
            details_str_parts.append(f"{k}={v}")
    details_str = ", ".join(details_str_parts)

    return f"[{timestamp}] [User: {user_info}] [Command: {display_command_name}] [Outcome: {outcome}] Details: {{{details_str}}}"

def log_command(interaction: discord.Interaction, command_name: str, outcome: str, **details) -> None:
    ensure_log_dir()
    # Determine guild_id, handling potential DM interactions gracefully
    if interaction.guild:
        guild_id = str(interaction.guild.id)
    else:
        guild_id = "dm_logs" # Log DMs to a separate file or handle as an error/unsupported

    log_file_path = os.path.join(LOG_DIR, f"{guild_id}.log")

    user = interaction.user
    message = format_log_message(user, command_name, outcome, details)

    try:
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(message + "\n")
    except Exception as e:
        print(f"Error writing to guild log {log_file_path}: {e}")

class AdminLogsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="viewlogs", description="View recent bot activity logs for this server")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(limit="Number of recent entries to show (max 50)")
    async def viewlogs(self, interaction: discord.Interaction, limit: int = 20):
        if limit > 50:
            limit = 50
        
        logger = get_comprehensive_logger(self.bot)
        logs = logger.get_guild_log_summary(interaction.guild.id, limit)
        
        if not logs:
            await interaction.response.send_message("No logs found for this server.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"Recent Bot Activity - {interaction.guild.name}",
            description=f"Showing last {len(logs)} entries",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        for log in logs[-10:]:  # Show last 10 in embed
            timestamp = log['timestamp']
            category = log['category']
            action = log['action']
            details = log['details']
            user = log.get('user', {}).get('name', 'System')
            
            embed.add_field(
                name=f"{category}: {action}",
                value=f"**Time:** {timestamp}\n**User:** {user}\n**Details:** {details}"[:1024],
                inline=False
            )
        
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Add this logging call
        log_details = {'limit': limit}
        # The variable 'logs' here is the result from logger.get_guild_log_summary
        log_outcome_message = "Displayed recent bot activity logs" if logs else "No logs found for this server"
        log_command(interaction, "/viewlogs", log_outcome_message, **log_details)

async def setup(bot):
    await bot.add_cog(AdminLogsCog(bot))
