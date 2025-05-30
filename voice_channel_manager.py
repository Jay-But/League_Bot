import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
from datetime import datetime

CONFIG_FILE = "voice_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

class VoiceChannelManagerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_ids = set()
        self.team_channels = {}

    async def log_action(self, guild: discord.Guild, action: str, details: str):
        config = load_config()
        logs_channel_id = config.get("logs")
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Voice Channel Management: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                await logs_channel.send(embed=embed)

    async def cog_unload(self):
        for channels in self.team_channels.values():
            for channel in channels[:-1]:
                if channel:
                    try:
                        await channel.delete()
                    except:
                        pass

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        for game_id, channels in list(self.team_channels.items()):
            if len(channels) > 2 and channels[2] == thread.id:
                for channel in channels[:2]:
                    if channel:
                        try:
                            await channel.delete()
                        except:
                            pass
                del self.team_channels[game_id]
                await self.log_action(thread.guild, "Thread Cleanup", f"Deleted voice channels for thread {thread.id}")

    async def create_team_voice_channels(self, guild: discord.Guild, team1_name: str, team2_name: str, category_id: str = None):
        category = guild.get_channel(int(category_id)) if category_id else None
        if not category:
            category = await guild.create_category("Game Voice Channels")

        team1_role = discord.utils.get(guild.roles, name=team1_name)
        team2_role = discord.utils.get(guild.roles, name=team2_name)
        if not team1_role or not team2_role:
            return None, None

        team1_channel = await category.create_voice_channel(f"{team1_name} Voice")
        team2_channel = await category.create_voice_channel(f"{team2_name} Voice")

        await team1_channel.set_permissions(guild.default_role, connect=False, view_channel=False)
        await team1_channel.set_permissions(team1_role, connect=True, view_channel=True)
        await team1_channel.send(f"{team1_role.mention} Your voice channel is ready!")

        await team2_channel.set_permissions(guild.default_role, connect=False, view_channel=False)
        await team2_channel.set_permissions(team2_role, connect=True, view_channel=True)
        await team2_channel.send(f"{team2_role.mention} Your voice channel is ready!")

        return team1_channel, team2_channel

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="create_vc", description="Create temporary voice channels for a scheduled game.")
    @app_commands.describe(game_id="Game identifier (e.g., Team1 vs Team2)")
    async def create_vc(self, interaction: discord.Interaction, game_id: str):
        config = load_config()
        schedule = load_schedule()  # Assuming load_schedule from ScheduleCog
        teams = schedule.get(game_id)
        if not teams:
            await interaction.response.send_message(f"No game found for '{game_id}'.", ephemeral=True)
            return

        team1, team2 = teams["team_a"], teams["team_b"]
        channel_name = f"{team1}-{team2}"
        category_id = config.get("voice_category_id")
        if not category_id:
            await interaction.response.send_message("No voice category set. Use /set_voice_category.", ephemeral=True)
            return

        team1_channel, team2_channel = await self.create_team_voice_channels(interaction.guild, team1, team2, category_id)
        if team1_channel and team2_channel:
            self.team_channels[channel_name] = [team1_channel, team2_channel]
            self.channel_ids.add(str(team1_channel.id))
            self.channel_ids.add(str(team2_channel.id))
            await interaction.response.send_message(
                f"Created voice channels: {team1_channel.mention} and {team2_channel.mention}",
                ephemeral=True
            )
            await self.log_action(interaction.guild, "Voice Channels Created", f"For {team1} vs {team2}")
        else:
            await interaction.response.send_message("Failed to create voice channels.", ephemeral=True)

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="delete_vc", description="Delete voice channels for a game.")
    @app_commands.describe(team1="First team", team2="Second team")
    async def delete_vc(self, interaction: discord.Interaction, team1: str, team2: str):
        game_id = f"{team1}-{team2}"
        if game_id not in self.team_channels:
            await interaction.response.send_message("No voice channels found for this game.", ephemeral=True)
            return

        channels = self.team_channels[game_id]
        thread_id = channels[2] if len(channels) > 2 else None

        for channel in channels[:2]:
            if channel:
                try:
                    await channel.delete()
                    self.channel_ids.discard(str(channel.id))
                except:
                    pass

        if thread_id:
            thread = interaction.guild.get_thread(thread_id)
            if thread:
                await thread.delete()

        del self.team_channels[game_id]
        await interaction.response.send_message("Deleted voice channels and thread.", ephemeral=True)
        await self.log_action(interaction.guild, "Voice Channels Deleted", f"For {team1} vs {team2}")

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="list_vcs", description="List all active temporary voice channels.")
    async def list_vcs(self, interaction: discord.Interaction):
        if not self.channel_ids:
            await interaction.response.send_message("No active voice channels.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Active Voice Channels",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        for game_id, channels in self.team_channels.items():
            channel_mentions = [c.mention for c in channels[:2] if c]
            embed.add_field(
                name=game_id,
                value=", ".join(channel_mentions) or "None",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # CPU Break
    # asyncio.sleep(2)

    @app_commands.command(name="set_voice_category", description="Set the voice channel category for temporary voice channels.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(category="The voice channel category")
    async def set_voice_category(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        config = load_config()
        config["voice_category_id"] = str(category.id)
        save_config(config)
        await interaction.response.send_message(f"Voice category set to: {category.name}", ephemeral=True)
        await self.log_action(interaction.guild, "Voice Category Set", f"Category: {category.name}")

    # CPU Break
    # asyncio.sleep(2)

async def setup(bot):
    await bot.add_cog(VoiceChannelManagerCog(bot))