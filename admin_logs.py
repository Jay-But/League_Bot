import discord
from discord import app_commands
from discord.ext import commands
import json

class AdminLogsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="viewlogs", description="View recent bot activity logs for this server")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(limit="Number of recent entries to show (max 50)")
    async def viewlogs(self, interaction: discord.Interaction, limit: int = 20):
        if limit > 50:
            limit = 50
        
        logs = []
        
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

async def setup(bot):
    await bot.add_cog(AdminLogsCog(bot))
