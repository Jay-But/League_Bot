import discord
from discord.ext import commands
import os
import asyncio
import logging
from utils.comprehensive_logger import get_comprehensive_logger

# Set up logging
logging.basicConfig(level=logging.INFO)

bot = commands.Bot(
    command_prefix="!",
    intents=discord.Intents.all()
)

async def load_extensions():
    extensions = [
        'cogs.draft',
        'cogs.emojis',
        'cogs.free_agency',
        'cogs.game_management',
        'cogs.multitrade',
        'cogs.retire_player',
        'cogs.schedule',
        'cogs.setup_cog',
        'cogs.templates',
        'cogs.transactions',
        'cogs.voice_channel_manager',
        'cogs.team_registration',
        'cogs.admin_logs'
    ]

    for extension in extensions:
        try:
            await bot.load_extension(extension)
            print(f"Loaded extension: {extension}")
        except Exception as e:
            print(f"Failed to load extension {extension}: {e}")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})')

    # Load extensions
    await load_extensions()

    # Initialize comprehensive logger
    logger = get_comprehensive_logger(bot)
    
    # Log bot startup for all guilds
    for guild in bot.guilds:
        await logger.log_bot_event(guild, "BOT_STARTUP", f"Bot started and ready in {guild.name}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.event
async def on_interaction(interaction):
    """Log all slash command usage"""
    if interaction.type == discord.InteractionType.application_command:
        logger = get_comprehensive_logger(bot)
        await logger.log_command_usage(interaction)

@bot.event
async def on_guild_join(guild):
    # guild_logger = get_guild_logger(bot) # Assuming get_guild_logger is defined elsewhere or in an extension
    # await guild_logger.log_guild_join(guild) # Assuming log_guild_join is a method of the guild_logger
    print(f"Bot joined guild: {guild.name} (ID: {guild.id})")

@bot.event
async def on_guild_remove(guild):
    # guild_logger = get_guild_logger(bot) # Assuming get_guild_logger is defined elsewhere or in an extension
    # await guild_logger.log_guild_remove(guild) # Assuming log_guild_remove is a method of the guild_logger
    print(f"Bot removed from guild: {guild.name} (ID: {guild.id})")

if __name__ == "__main__":
    # Get the bot token from environment variable
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if TOKEN is None:
        raise ValueError("DISCORD_BOT_TOKEN environment variable is not set. Please add your bot token to the Secrets tab.")

    bot.run(TOKEN)