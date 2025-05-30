# Adding autocomplete to teamclaim command
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime
import pytz
import asyncio

CONFIG_FILE = "config/setup.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def load_guild_config(guild_id):
    """Load guild-specific configuration"""
    config_file = f"config/setup_{guild_id}.json"
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}

def save_guild_config(guild_id, config):
    """Save guild-specific configuration"""
    os.makedirs("config", exist_ok=True)
    config_file = f"config/setup_{guild_id}.json"
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=4)

class FreeAgencyCog(commands.Cog):
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

    def get_free_agency_channel(self, guild):
        """Get the configured free agency channel"""
        guild_config = self.get_guild_config(guild.id)
        channels_config = guild_config.get("channels", {})
        free_agency_channel_id = channels_config.get("free_agency")

        if free_agency_channel_id:
            return guild.get_channel(free_agency_channel_id)
        return None

    def get_candidate_role(self, guild):
        """Get the configured candidate role"""
        guild_config = self.get_guild_config(guild.id)
        roles_config = guild_config.get("roles", {})
        candidate_role_id = roles_config.get("candidate")

        if candidate_role_id:
            return guild.get_role(candidate_role_id)
        return None

    async def log_action(self, guild, action, details):
        config = self.get_guild_config(guild.id)
        logs_channel_id = config.get("channels", {}).get("logs")
        if logs_channel_id:
            logs_channel = guild.get_channel(int(logs_channel_id))
            if logs_channel:
                embed = discord.Embed(
                    title=f"Free Agency: {action}",
                    description=details,
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                await logs_channel.send(embed=embed)

    def get_team_info(self, member: discord.Member):
        config = self.get_guild_config(member.guild.id)
        team_emojis = config.get("team_emojis", {})
        teams = config.get("teams", [])

        for role in member.roles:
            if role.name in teams and role.name != "@everyone":
                emoji = team_emojis.get(role.name, "")
                return role, role.name, emoji
        return None, None, None

    def has_franchise_role(self, member: discord.Member):
        config = self.get_guild_config(member.guild.id)
        franchise_roles = ["franchise_owner", "general_manager", "head_coach", "assistant_coach"]
        roles_config = config.get("roles", {})

        for role_key in franchise_roles:
            role_id = roles_config.get(role_key)
            if role_id:
                role = discord.utils.get(member.guild.roles, id=int(role_id))
                if role and role in member.roles:
                    return True
        return False

    def has_verified_role(self, member: discord.Member):
        config = self.get_guild_config(member.guild.id)
        verified_role_id = config.get("roles", {}).get("verified")
        if verified_role_id:
            verified_role = discord.utils.get(member.guild.roles, id=int(verified_role_id))
            if verified_role and verified_role in member.roles:
                return True
        return False

    @app_commands.command(name="freeagency", description="Submit a free agency form.")
    @app_commands.describe(form_type="The type of free agency form to submit")
    @app_commands.choices(form_type=[
        app_commands.Choice(name="Free Agent", value="free_agent"),
        app_commands.Choice(name="Player", value="player"),
        app_commands.Choice(name="Team Staff", value="team_staff")
    ])
    async def freeagency(self, interaction: discord.Interaction, form_type: str):
        # Check if guild is configured
        config = self.get_guild_config(interaction.guild.id)
        if not config:
            await interaction.response.send_message("❌ This server hasn't been configured yet. Please ask an administrator to run `/setup` first.", ephemeral=True)
            return

        team_role, team_name, _ = self.get_team_info(interaction.user)
        teams = config.get("teams", [])
        has_team = team_name in teams
        is_staff = self.has_franchise_role(interaction.user)
        is_verified = self.has_verified_role(interaction.user)

        if form_type == "free_agent":
            if not is_verified:
                await interaction.response.send_message("You must have the Verified role to submit a Free Agent form.", ephemeral=True)
                return
            if has_team:
                await interaction.response.send_message("You cannot submit a Free Agent form while on a team.", ephemeral=True)
                return
        elif form_type == "player" and not has_team:
            await interaction.response.send_message("You must be on a team to submit a Player form.", ephemeral=True)
            return
        elif form_type == "team_staff" and not is_staff:
            await interaction.response.send_message("Only franchise staff can submit a Team Staff form.", ephemeral=True)
            return

        questions = {
            "free_agent": [
                "What are your positions?",
                "Which teams do you hope to get signed to?",
                "Roblox Username",
                "Previous teams (or 'none')"
            ],
            "player": [
                "What are your positions?",
                "Which teams are you hoping to transition to?",
                "Former and current teams you played for",
                "Roblox Username"
            ],
            "team_staff": [
                "What staff positions are you looking for?",
                "What is your current team's name?",
                "What experience do you want a player to have?",
                "Who is the player you're interested in?",
                "Team chat link (Discord invite link)"
            ]
        }

        class FreeAgencyModal(discord.ui.Modal):
            def __init__(self, form_type, questions, cog):
                super().__init__(title=f"{form_type.replace('_', ' ').title()} Form")
                self.form_type = form_type
                self.cog = cog
                for i, question in enumerate(questions):
                    self.add_item(discord.ui.TextInput(
                        label=question,
                        custom_id=f"q{i}",
                        style=discord.TextStyle.paragraph
                    ))

            async def on_submit(self, interaction: discord.Interaction):
                embed = discord.Embed(
                    title=f"{self.form_type.replace('_', ' ').title()} Form Submission",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                for item in self.children:
                    embed.add_field(
                        name=item.label,
                        value=item.value or "N/A",
                        inline=False
                    )
                embed.set_author(
                    name=f"{interaction.user.display_name} ({interaction.user.id})",
                    icon_url=interaction.user.avatar.url if interaction.user.avatar else None
                )
                if interaction.guild.icon:
                    embed.set_thumbnail(url=interaction.guild.icon.url)

                # Get guild-specific configuration
                config = self.cog.get_guild_config(interaction.guild.id)
                free_agency_channel_id = config.get("channels", {}).get("free_agency")

                if not free_agency_channel_id:
                    await interaction.response.send_message("❌ Free Agency channel not configured. Please ask an administrator to run `/setup` and configure the Free Agency channel.", ephemeral=True)
                    return

                free_agency_channel = interaction.guild.get_channel(int(free_agency_channel_id))
                if not free_agency_channel:
                    await interaction.response.send_message("❌ Free Agency channel not found. The configured channel may have been deleted.", ephemeral=True)
                    return

                view = discord.ui.View(timeout=None)  # Persistent view
                if self.form_type == "free_agent":
                    offer_button = discord.ui.Button(
                        label="Offer",
                        style=discord.ButtonStyle.green,
                        custom_id=f"offer_{interaction.user.id}"
                    )
                    offer_button.callback = self.cog.offer_button_callback(interaction.user)
                    view.add_item(offer_button)
                elif self.form_type == "player":
                    trade_button = discord.ui.Button(
                        label="Trade For",
                        style=discord.ButtonStyle.green,
                        custom_id=f"trade_{interaction.user.id}"
                    )
                    trade_button.callback = self.cog.trade_button_callback(interaction.user)
                    view.add_item(trade_button)

                delete_button = discord.ui.Button(
                    label="Delete",
                    style=discord.ButtonStyle.red,
                    custom_id=f"delete_{interaction.user.id}"
                )
                delete_button.callback = self.cog.delete_button_callback(interaction.user)
                view.add_item(delete_button)

                await free_agency_channel.send(embed=embed, view=view)
                await interaction.response.send_message("✅ Form submitted successfully!", ephemeral=True)
                await self.cog.log_action(
                    interaction.guild,
                    "Form Submitted",
                    f"{interaction.user.display_name} submitted {self.form_type} form"
                )

        modal = FreeAgencyModal(form_type, questions[form_type], self)
        await interaction.response.send_modal(modal)

    def offer_button_callback(self, submitter: discord.Member):
        async def callback(interaction: discord.Interaction):
            if not self.has_franchise_role(interaction.user):
                await interaction.response.send_message("Only franchise roles can make offers.", ephemeral=True)
                return
            await interaction.response.send_message(
                f"Use `/offer {submitter.id}` to send a contract offer to {submitter.mention}.",
                ephemeral=True
            )
        return callback

    def trade_button_callback(self, submitter: discord.Member):
        async def callback(interaction: discord.Interaction):
            if not self.has_franchise_role(interaction.user):
                await interaction.response.send_message("Only franchise roles can propose trades.", ephemeral=True)
                return
            team_role, team_name, _ = self.get_team_info(submitter)
            if not team_name:
                await interaction.response.send_message(f"{submitter.display_name} is not on a team.", ephemeral=True)
                return
            await interaction.response.send_message(
                f"Use `/trade offered_player:<your_player> targeted_team:{team_name} targeted_player:{submitter.id}` to propose a trade for {submitter.mention}.",
                ephemeral=True
            )
        return callback

    def delete_button_callback(self, submitter: discord.Member):
        async def callback(interaction: discord.Interaction):
            # Extract author ID from embed author name
            author_name = interaction.message.embeds[0].author.name
            # Parse the ID from the format "Display Name (ID)"
            author_id = int(author_name.split("(")[-1].split(")")[0])

            if interaction.user.id != author_id:
                await interaction.response.send_message("Only the form submitter can delete this form.", ephemeral=True)
                return
            await interaction.message.delete()
            await interaction.response.send_message("Form deleted successfully.", ephemeral=True)
            await self.log_action(
                interaction.guild,
                "Form Deleted",
                f"{interaction.user.display_name} deleted their {interaction.message.embeds[0].title}"
            )
        return callback

    async def team_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        config = self.get_guild_config(interaction.guild.id)
        teams = config.get("teams", [])
        return [
            app_commands.Choice(name=team, value=team)
            for team in teams if current.lower() in team.lower()
        ]

    @app_commands.command(name="teamclaim", description="Claim a free agent for your team.")
    @app_commands.describe(player="The free agent to claim", team="The team claiming the player")
    @app_commands.autocomplete(team=team_autocomplete)
    async def teamclaim(self, interaction: discord.Interaction, player: discord.Member, team: str):
        await interaction.response.send_message("This command is under development.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(FreeAgencyCog(bot))