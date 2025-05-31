import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from .team_management import team_autocomplete

class Templates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="templates")
    async def templates(self, interaction: discord.Interaction):
        """Shows links to various types of templates."""
        embed = discord.Embed(
            title="Templates Collection",
            description="Here are some general templates you can explore:",
            color=discord.Color.blue()
        )

        # Add your template links here (Replace with actual URLs or file links)
        embed.add_field(
            name="Template 1: Ultimate Football Template",
            value="[Click here to view the template](https://discord.new/HEXRXxtwdfw8)"
        )
        embed.add_field(
            name="Template 2: College Football Template",
            value="[Click here to view the template]( https://discord.new/uQKaKW4XQEeU)"
        )
        embed.add_field(
            name="Template 3: NFL Template",
            value="[Click here to view the template](https://discord.new/tYcyXuncxYWz)"
        )
        embed.add_field(
            name="Template 4: College Football Template",
            value="[Click here to view the template](https://discord.new/dCam3QbGhkf3)"
        )
        embed.add_field(
            name="Template 5: NFL Template",
            value="[Click here to view the template](https://discord.new/jrtrxWR4zQpP)"
        )
        embed.add_field(
            name="Template 6: Soccer Template",
            value="[Click here to view the template](https://discord.new/PUgQUrDG8dq8)"
        )
        embed.add_field(
            name="Template 7: TC Template",
            value="[Click here to view the template](https://discord.new/98Am5gmp74nY)"
        )
        embed.add_field(
            name="Template 8: TC Template",
            value="[Click here to view the template](https://discord.new/KPT3XzfxjXeA)"
        )
        embed.add_field(
            name="Template 9: TC Template",
            value="[Click here to view the template](https://discord.new/VY697cUV7HxU)"
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="teamtemplate", description="Create a template message for a team.")
    @app_commands.describe(team="The team to create template for", template_type="Type of template")
    @app_commands.autocomplete(team=team_autocomplete)
    async def teamtemplate(self, interaction: discord.Interaction, team: str, template_type: str):
        """Create a template message for a specific team."""
        # Implement the logic for creating team-specific templates here
        await interaction.response.send_message(f"Template for team {team} of type {template_type} will be created.", ephemeral=True)

async def setup(bot):
    """Load the templates cog."""
    await bot.add_cog(Templates(bot))