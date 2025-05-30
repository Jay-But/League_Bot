import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime
import pytz
import aiohttp
import asyncio

CONFIG_FILE = "config/setup.json"
EMOJIS_FILE = "emojis.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def load_emoji_config():
    if os.path.exists(EMOJIS_FILE):
        with open(EMOJIS_FILE, 'r') as f:
            return json.load(f)
    return {}

class EmojiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()
        self.emoji_config = load_emoji_config()
        self.team_emojis = self.config.get("team_emojis", {})

    async def log_action(self, guild, action, details):
        logs_channel_id = self.config.get("logs_channel")
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Emoji Management: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Guild", value=f"{guild.name} (ID: {guild.id})", inline=True)
                embed.add_field(name="Member Count", value=str(guild.member_count), inline=True)
                if guild.icon:
                    embed.set_footer(text=f"Guild ID: {guild.id}", icon_url=guild.icon.url)
                else:
                    embed.set_footer(text=f"Guild ID: {guild.id}")
                await logs_channel.send(embed=embed)

    @app_commands.command(name="addemojis", description="Add all NFL team emojis to the server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def addemojis(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Map team names to local file names
        team_files = {
            "Arizona Cardinals": "4178-cardinals.png",
            "Atlanta Falcons": "3177-falcons.png",
            "Baltimore Ravens": "4375-ravens.png",
            "Buffalo Bills": "3207-bills.png",
            "Carolina Panthers": "1804-panthers.png",
            "Chicago Bears": "3410-bears.png",
            "Cincinnati Bengals": "8315-bengals.png",
            "Cleveland Browns": "3410-browns.png",
            "Dallas Cowboys": "9528-cowboys.png",
            "Denver Broncos": "2225-broncos.png",
            "Detroit Lions": "78843-lions.png",
            "Green Bay Packers": "7983-packers.png",
            "Houston Texans": "3615-texans.png",
            "Indianapolis Colts": "8534-coltslogo.png",
            "Jacksonville Jaguars": "3023-jaguars.png",
            "Kansas City Chiefs": "8133-chiefs.png",
            "Las Vegas Raiders": "1804-raiders.png",
            "Los Angeles Chargers": "7279-chargers.png",
            "Los Angeles Rams": "9246-rams.png",
            "Miami Dolphins": "5058-dolphins.png",
            "Minnesota Vikings": "3487-vikings.png",
            "New England Patriots": "4570-patriots.png",
            "New Orleans Saints": "9462-saints.png",
            "New York Giants": "4173-giants.png",
            "New York Jets": "3960-jets.png",
            "Philadelphia Eagles": "5949-eagles.png",
            "Pittsburgh Steelers": "5156-steelers.png",
            "San Francisco 49ers": "4375-49ers.png",
            "Seattle Seahawks": "7454-seahawks2.png",
            "Tampa Bay Buccaneers": "4991-tbucca.png",
            "Tennessee Titans": "8038-titans.png",
            "Washington Commanders": "1310-commanders.png"
        }

        success_count = 0
        failed_teams = []

        for team_name, filename in team_files.items():
            try:
                # Read local file
                file_path = f"attached_assets/{filename}"
                if not os.path.exists(file_path):
                    failed_teams.append(f"{team_name} (file not found: {filename})")
                    continue

                with open(file_path, 'rb') as f:
                    image_data = f.read()

                # Create emoji name from team name
                emoji_name = team_name.lower().replace(' ', '_').replace('-', '_')
                emoji_name = ''.join(c for c in emoji_name if c.isalnum() or c == '_')

                # Check if emoji already exists
                existing_emoji = discord.utils.get(interaction.guild.emojis, name=emoji_name)
                if existing_emoji:
                    self.team_emojis[team_name] = str(existing_emoji)
                    continue

                new_emoji = await interaction.guild.create_custom_emoji(name=emoji_name, image=image_data)
                self.team_emojis[team_name] = str(new_emoji)
                success_count += 1

                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)

            except discord.errors.HTTPException as e:
                if "Maximum number of emojis reached" in str(e):
                    failed_teams.append(f"{team_name} (Server emoji limit reached)")
                    break
                else:
                    failed_teams.append(f"{team_name} (Discord error: {str(e)[:50]})")
            except Exception as e:
                failed_teams.append(f"{team_name} (Error: {str(e)[:50]})")

        # Save updated config
        self.config["team_emojis"] = self.team_emojis
        save_config(self.config)

        # Create response embed
        embed = discord.Embed(
            title="NFL Team Emojis Added",
            color=discord.Color.green() if success_count > 0 else discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )

        if success_count > 0:
            embed.add_field(name="Successfully Added", value=f"{success_count} NFL team emojis", inline=False)

        if failed_teams:
            failed_text = "\n".join(failed_teams[:10])  # Limit to 10 to avoid embed limits
            if len(failed_teams) > 10:
                failed_text += f"\n... and {len(failed_teams) - 10} more"
            embed.add_field(name="Failed", value=failed_text, inline=False)

        if success_count == 0 and not failed_teams:
            embed.description = "All NFL team emojis already exist in this server."
            embed.color = discord.Color.blue()

        embed.add_field(name="Total NFL Teams", value=f"{len(team_files)} teams configured", inline=True)

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.followup.send(embed=embed)
        await self.log_action(
            interaction.guild, 
            "NFL Team Emojis Added", 
            f"Added {success_count} emojis, {len(failed_teams)} failed"
        )

    @app_commands.command(name="removeemojis", description="Remove all NFL team emojis from the server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeemojis(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not self.team_emojis:
            await interaction.followup.send("No team emojis found to remove.", ephemeral=True)
            return

        removed_count = 0
        failed_removals = []

        for team_name, emoji_str in list(self.team_emojis.items()):
            try:
                if emoji_str.startswith("<:") or emoji_str.startswith("<a:"):
                    emoji_id = int(emoji_str.split(":")[-1].rstrip(">"))
                    emoji = discord.utils.get(interaction.guild.emojis, id=emoji_id)
                    if emoji:
                        await emoji.delete()
                        removed_count += 1
                    del self.team_emojis[team_name]
            except Exception as e:
                failed_removals.append(f"{team_name}: {str(e)[:50]}")

        # Save updated config
        self.config["team_emojis"] = self.team_emojis
        save_config(self.config)

        embed = discord.Embed(
            title="NFL Team Emojis Removed",
            color=discord.Color.red() if removed_count > 0 else discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )

        if removed_count > 0:
            embed.add_field(name="Successfully Removed", value=f"{removed_count} NFL team emojis", inline=False)

        if failed_removals:
            failed_text = "\n".join(failed_removals[:10])
            if len(failed_removals) > 10:
                failed_text += f"\n... and {len(failed_removals) - 10} more"
            embed.add_field(name="Failed to Remove", value=failed_text, inline=False)

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.followup.send(embed=embed)
        await self.log_action(
            interaction.guild, 
            "NFL Team Emojis Removed", 
            f"Removed {removed_count} emojis, {len(failed_removals)} failed"
        )

    @app_commands.command(name="listemojis", description="List all configured NFL team emojis.")
    async def listemojis(self, interaction: discord.Interaction):
        nfl_teams = self.emoji_config.get("teams", {})

        if not nfl_teams:
            await interaction.response.send_message("No NFL teams configured in emojis.json.", ephemeral=True)
            return

        embed = discord.Embed(
            title="NFL Team Emojis Configuration",
            description=f"Total teams: {len(nfl_teams)}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # Split teams into chunks for multiple fields
        team_list = list(nfl_teams.keys())
        chunk_size = 10
        for i in range(0, len(team_list), chunk_size):
            chunk = team_list[i:i + chunk_size]
            field_name = f"Teams ({i+1}-{min(i+chunk_size, len(team_list))})"
            field_value = "\n".join(chunk)
            embed.add_field(name=field_name, value=field_value, inline=True)

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(EmojiCog(bot))