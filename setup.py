import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime, timedelta

class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = self.load_config()

    def load_config(self):
        CONFIG_FILE = "config/setup.json"
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {}

    def load_guild_config(self, guild_id):
        """Load guild-specific configuration"""
        config_file = f"config/setup_{guild_id}.json"
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                return json.load(f)
        return {}

    def save_config(self, guild_id, config):
        os.makedirs("config", exist_ok=True)
        with open(f"config/setup_{guild_id}.json", 'w') as f:
            json.dump(config, f, indent=4)

    @app_commands.command(name="setupstatus", description="Check the current setup configuration.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupstatus(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        guild_config_file = f"config/setup_{guild_id}.json"

        if not os.path.exists(guild_config_file):
            await interaction.response.send_message("❌ No setup configuration found. Please run `/setup` first.", ephemeral=True)
            return

        try:
            with open(guild_config_file, 'r') as f:
                content = f.read().strip()
                if not content:
                    await interaction.response.send_message("❌ Setup configuration file is empty. Please run `/setup` and save the configuration.", ephemeral=True)
                    return

                guild_config = json.loads(content)

                embed = discord.Embed(
                    title="🏈 Setup Configuration Status",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )

                # Check roles
                roles_config = guild_config.get("roles", {})
                role_status = []
                required_roles = ["candidate", "franchise_owner"]

                for role_key in required_roles:
                    role_id = roles_config.get(role_key)
                    if role_id:
                        role = interaction.guild.get_role(role_id)
                        status = f"✅ {role.mention}" if role else f"❌ Role ID {role_id} not found"
                    else:
                        status = "❌ Not configured"
                    role_status.append(f"**{role_key.replace('_', ' ').title()}:** {status}")

                embed.add_field(
                    name="Required Roles", 
                    value="\n".join(role_status),
                    inline=False
                )

                # Show all configured roles
                all_roles = []
                for role_key, role_id in roles_config.items():
                    role = interaction.guild.get_role(role_id)
                    role_name = role.mention if role else f"ID: {role_id} (deleted)"
                    all_roles.append(f"{role_key}: {role_name}")

                if all_roles:
                    embed.add_field(
                        name="All Configured Roles",
                        value="\n".join(all_roles[:10]),  # Limit to avoid embed limit
                        inline=False
                    )

                await interaction.response.send_message(embed=embed, ephemeral=True)

        except json.JSONDecodeError:
            await interaction.response.send_message("❌ Setup configuration file is corrupted. Please run `/setup` again.", ephemeral=True)

    @app_commands.command(name="setup", description="Configure the league settings with /setup.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        config = self.load_guild_config(guild_id)

        # Initialize all data structures
        franchise_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
        additional_roles_1 = ["Admin", "Moderator", "Candidate", "Referee"]
        additional_roles_2 = ["Streamer", "Suspended", "Blacklisted", "Verified"]
        league_channels = ["Transactions", "Gametime", "Scores", "Free Agency"]
        additional_channels = ["Suspensions", "Logs", "Owners", "Alerts"]
        schedule_channels = ["Schedule"]

        role_selections = {role: config.get("roles", {}).get(role.lower().replace(" ", "_"), None) for role in franchise_roles + additional_roles_1 + additional_roles_2}
        channel_selections = {channel: config.get("channels", {}).get(channel.lower().replace(" ", "_"), None) for channel in league_channels + additional_channels + schedule_channels}
        settings = {
            "roster_cap": config.get("roster_cap", 53),
            "signings_mode": config.get("signings_mode", "offer"),
            "draft_enabled": config.get("draft_enabled", False),
            "trade_deadline": config.get("trade_deadline", (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M"))
        }

        # Start with page 1
        await self.show_page(interaction, 1, role_selections, channel_selections, settings, guild_id)

    async def show_page(self, interaction: discord.Interaction, page: int, role_selections, channel_selections, settings, guild_id, edit_response=False):
        total_pages = 7
        view = SetupView(self, page, total_pages, role_selections, channel_selections, settings, guild_id)
        embed = self.create_page_embed(page, total_pages, role_selections, channel_selections, settings, interaction.guild)

        if edit_response:
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def create_page_embed(self, page: int, total_pages: int, role_selections, channel_selections, settings, guild):
        if page == 1:
            embed = discord.Embed(
                title="🏈 League Setup", # Standardized title
                description=f"**Step {page}/{total_pages}: Franchise Roles**\nSelect roles for your league's franchise management.",
                color=discord.Color.blue()
            )
            franchise_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
            for role_name in franchise_roles:
                role_id = role_selections.get(role_name)
                if role_id:
                    role = guild.get_role(role_id)
                    value = role.mention if role else "Not found"
                else:
                    value = "Not set"
                embed.add_field(name=role_name, value=value, inline=True)

        elif page == 2:
            embed = discord.Embed(
                title="🏈 League Setup", # Standardized title
                description=f"**Step {page}/{total_pages}: Additional Roles**\nSelect additional roles for your league.",
                color=discord.Color.blue()
            )
            additional_roles_1 = ["Admin", "Moderator", "Candidate", "Referee"]
            for role_name in additional_roles_1:
                role_id = role_selections.get(role_name)
                if role_id:
                    role = guild.get_role(role_id)
                    value = role.mention if role else "Not found"
                else:
                    value = "Not set"
                embed.add_field(name=role_name, value=value, inline=True)

        elif page == 3:
            embed = discord.Embed(
                title="🏈 League Setup", # Standardized title
                description=f"**Step {page}/{total_pages}: More Roles**\nSelect additional roles for your league.",
                color=discord.Color.blue()
            )
            additional_roles_2 = ["Streamer", "Suspended", "Blacklisted", "Verified"]
            for role_name in additional_roles_2:
                role_id = role_selections.get(role_name)
                if role_id:
                    role = guild.get_role(role_id)
                    value = role.mention if role else "Not found"
                else:
                    value = "Not set"
                embed.add_field(name=role_name, value=value, inline=True)

        elif page == 4:
            embed = discord.Embed(
                title="🏈 League Setup", # Standardized title
                description=f"**Step {page}/{total_pages}: League Channels**\nSelect channels for your league.",
                color=discord.Color.blue()
            )
            league_channels = ["Transactions", "Gametime", "Scores", "Free Agency"]
            for channel_name in league_channels:
                channel_id = channel_selections.get(channel_name)
                if channel_id:
                    channel = guild.get_channel(channel_id)
                    value = channel.mention if channel else "Not found"
                else:
                    value = "Not set"
                embed.add_field(name=channel_name, value=value, inline=True)

        elif page == 5:
            embed = discord.Embed(
                title="🏈 League Setup", # Standardized title
                description=f"**Step {page}/{total_pages}: Additional Channels**\nSelect additional channels for your league.",
                color=discord.Color.blue()
            )
            additional_channels = ["Suspensions", "Logs", "Owners", "Alerts"]
            for channel_name in additional_channels:
                channel_id = channel_selections.get(channel_name)
                if channel_id:
                    channel = guild.get_channel(channel_id)
                    value = channel.mention if channel else "Not found"
                else:
                    value = "Not set"
                embed.add_field(name=channel_name, value=value, inline=True)

        elif page == 6:
            embed = discord.Embed(
                title="🏈 League Setup", # Standardized title
                description=f"**Step {page}/{total_pages}: Schedule Channel**\nSelect the channel where game schedules will be posted.",
                color=discord.Color.blue()
            )
            schedule_channel_id = channel_selections.get("Schedule")
            if schedule_channel_id:
                channel = guild.get_channel(schedule_channel_id)
                value = channel.mention if channel else "Not found"
            else:
                value = "Not set"
            embed.add_field(name="Schedule Channel", value=value, inline=False)

        elif page == 7:
            embed = discord.Embed(
                title="🏈 League Setup", # Standardized title
                description=f"**Step {page}/{total_pages}: Final Settings**\nConfigure your league's core settings and policies.",
                color=discord.Color.gold() # Keeping gold color for final page as per instructions
            )

            # Team Management Section
            embed.add_field(
                name="👥 Team Management", 
                value=f"**Roster Cap:** {settings['roster_cap']} players\n**Signings Mode:** `/{settings['signings_mode']}`", 
                inline=True
            )

            # League Operations Section  
            embed.add_field(
                name="⚙️ League Operations", 
                value=f"**Draft System:** {'🟢 Enabled' if settings['draft_enabled'] else '🔴 Disabled'}\n**Trade Deadline:** {settings['trade_deadline']}", 
                inline=True
            )

            # Integration Status
            roles_configured = len([r for r in role_selections.values() if r])
            channels_configured = len([c for c in channel_selections.values() if c])

            embed.add_field(
                name="🔗 Bot Integration Status",
                value=f"**Roles Configured:** {roles_configured}/12\n**Channels Configured:** {channels_configured}/8\n**Commands:** All connected to setup",
                inline=True
            )

            # Status Overview
            status_emoji = "✅" if all([settings['roster_cap'] > 0, settings['signings_mode'] in ['offer', 'sign', 'both']]) and roles_configured >= 2 and channels_configured >= 2 else "⚠️"
            embed.add_field(
                name=f"{status_emoji} Configuration Status", 
                value="All bot commands are now integrated with your setup configuration!\n\n**Connected Commands:**\n• `/sign`, `/offer`, `/release` - Use franchise roles\n• `/addteam`, `/listteams` - Use admin roles\n• All logs use configured channels", 
                inline=False
            )

        embed.set_footer(text=f"Last updated: {datetime.now().strftime('%I:%M %p CDT, %B %d, %Y')}")
        return embed

class SetupView(discord.ui.View):
    def __init__(self, cog, page: int, total_pages: int, role_selections, channel_selections, settings, guild_id):
        super().__init__(timeout=900)
        self.cog = cog
        self.page = page
        self.total_pages = total_pages
        self.role_selections = role_selections
        self.channel_selections = channel_selections
        self.settings = settings
        self.guild_id = guild_id

        self.setup_page_components()

    async def auto_save_config(self):
        """Automatically save configuration when changes are made"""
        role_mapping = {
            "Franchise Owner": "franchise_owner",
            "General Manager": "general_manager", 
            "Head Coach": "head_coach",
            "Assistant Coach": "assistant_coach",
            "Admin": "admin",
            "Moderator": "moderator",
            "Candidate": "candidate",
            "Referee": "referee",
            "Verified": "verified",
            "Streamer": "streamer",
            "Suspended": "suspended",
            "Blacklisted": "blacklisted"
        }

        channel_mapping = {
            "Transactions": "transactions",
            "Gametime": "gametime",
            "Scores": "scores", 
            "Free Agency": "free_agency",
            "Schedule": "schedule",
            "Suspensions": "suspensions",
            "Logs": "logs",
            "Owners": "owners",
            "Alerts": "alerts"
        }

        config = {
            "roles": {role_mapping.get(k, k.lower().replace(" ", "_")): v for k, v in self.role_selections.items() if v},
            "channels": {channel_mapping.get(k, k.lower().replace(" ", "_")): v for k, v in self.channel_selections.items() if v},
            "roster_cap": self.settings["roster_cap"],
            "signings_mode": self.settings["signings_mode"],
            "draft_enabled": self.settings["draft_enabled"],
            "trade_deadline": self.settings["trade_deadline"]
        }
        self.cog.save_config(self.guild_id, config)

    def setup_page_components(self):
        self.clear_items()

        if self.page == 1:
            franchise_roles = ["Franchise Owner", "General Manager", "Head Coach", "Assistant Coach"]
            for i, role_name in enumerate(franchise_roles):
                select = discord.ui.RoleSelect(
                    placeholder=f"Select {role_name} role",
                    custom_id=f"fr_{role_name.lower().replace(' ', '_')}",
                    max_values=1,
                    row=i
                )

                # Set default value if role is already selected
                if self.role_selections.get(role_name):
                    try:
                        role = discord.utils.get(self.view.message.guild.roles, id=self.role_selections[role_name])
                        if role:
                            select.default_values = [role]
                    except:
                        pass

                select.callback = self.create_role_callback(role_name)
                self.add_item(select)

        elif self.page == 2:
            additional_roles_1 = ["Admin", "Moderator", "Candidate", "Referee"]
            for i, role_name in enumerate(additional_roles_1):
                select = discord.ui.RoleSelect(
                    placeholder=f"Select {role_name} role",
                    custom_id=f"ar1_{role_name.lower().replace(' ', '_')}",
                    max_values=1,
                    row=i
                )
                select.callback = self.create_role_callback(role_name)
                self.add_item(select)

        elif self.page == 3:
            additional_roles_2 = ["Streamer", "Suspended", "Blacklisted", "Verified"]
            for i, role_name in enumerate(additional_roles_2):
                select = discord.ui.RoleSelect(
                    placeholder=f"Select {role_name} role",
                    custom_id=f"ar2_{role_name.lower().replace(' ', '_')}",
                    max_values=1,
                    row=i
                )
                select.callback = self.create_role_callback(role_name)
                self.add_item(select)

        elif self.page == 4:
            league_channels = ["Transactions", "Gametime", "Scores", "Free Agency"]
            for i, channel_name in enumerate(league_channels):
                select = discord.ui.ChannelSelect(
                    placeholder=f"Select {channel_name} channel",
                    custom_id=f"ch_{channel_name.lower().replace(' ', '_')}",
                    max_values=1,
                    channel_types=[discord.ChannelType.text],
                    row=i
                )
                select.callback = self.create_channel_callback(channel_name)
                self.add_item(select)

        elif self.page == 5:
            additional_channels = ["Suspensions", "Logs", "Owners", "Alerts"]
            for i, channel_name in enumerate(additional_channels):
                select = discord.ui.ChannelSelect(
                    placeholder=f"Select {channel_name} channel",
                    custom_id=f"ch_{channel_name.lower().replace(' ', '_')}",
                    max_values=1,
                    channel_types=[discord.ChannelType.text],
                    row=i
                )
                select.callback = self.create_channel_callback(channel_name)
                self.add_item(select)

        elif self.page == 6:
            schedule_select = discord.ui.ChannelSelect(
                placeholder="Select Schedule channel",
                custom_id="ch_schedule",
                max_values=1,
                channel_types=[discord.ChannelType.text],
                row=0
            )
            schedule_select.callback = self.create_channel_callback("Schedule")
            self.add_item(schedule_select)

        elif self.page == 7:
            # Settings buttons
            roster_cap_button = discord.ui.Button(
                label="📊 Roster Cap", 
                style=discord.ButtonStyle.primary, 
                custom_id="roster_cap_modal", 
                row=0
            )
            roster_cap_button.callback = self.roster_cap_modal

            signings_mode_button = discord.ui.Button(
                label=f"✍️ Signings: /{self.settings['signings_mode']}", 
                style=discord.ButtonStyle.secondary, 
                custom_id="signings_mode_toggle", 
                row=0
            )
            signings_mode_button.callback = self.signings_mode_toggle

            draft_toggle_button = discord.ui.Button(
                label=f"🎯 Draft: {'ON' if self.settings['draft_enabled'] else 'OFF'}", 
                style=discord.ButtonStyle.success if self.settings['draft_enabled'] else discord.ButtonStyle.danger, 
                custom_id="draft_toggle", 
                row=1
            )
            draft_toggle_button.callback = self.draft_toggle

            trade_deadline_button = discord.ui.Button(
                label="📅 Trade Deadline", 
                style=discord.ButtonStyle.primary, 
                custom_id="trade_deadline_modal", 
                row=1
            )
            trade_deadline_button.callback = self.trade_deadline_modal

            self.add_item(roster_cap_button)
            self.add_item(signings_mode_button)
            self.add_item(draft_toggle_button)
            self.add_item(trade_deadline_button)

        # Add navigation buttons
        nav_row = 4
        if self.page > 1:
            back_button = discord.ui.Button(label="◀️ Back", style=discord.ButtonStyle.secondary, row=nav_row)
            back_button.callback = self.back_page
            self.add_item(back_button)

        if self.page < self.total_pages:
            next_button = discord.ui.Button(label="Next ▶️", style=discord.ButtonStyle.green, row=nav_row)
            next_button.callback = self.next_page
            self.add_item(next_button)

        if self.page == self.total_pages:
            close_button = discord.ui.Button(label="✅ Setup Complete", style=discord.ButtonStyle.success, row=nav_row)
            close_button.callback = self.close_setup
            self.add_item(close_button)

    def create_role_callback(self, role_name):
        async def role_callback(interaction: discord.Interaction):
            select = interaction.data["values"][0] if interaction.data.get("values") else None
            if select:
                self.role_selections[role_name] = int(select)
                role = interaction.guild.get_role(int(select))
                await interaction.response.send_message(f"✅ {role_name} role set to {role.mention}", ephemeral=True)
            else:
                self.role_selections[role_name] = None
                await interaction.response.send_message(f"❌ {role_name} role cleared", ephemeral=True)

            # Auto-save configuration
            await self.auto_save_config()
        return role_callback

    def create_channel_callback(self, channel_name):
        async def channel_callback(interaction: discord.Interaction):
            select = interaction.data["values"][0] if interaction.data.get("values") else None
            if select:
                self.channel_selections[channel_name] = int(select)
                channel = interaction.guild.get_channel(int(select))
                await interaction.response.send_message(f"✅ {channel_name} channel set to {channel.mention}", ephemeral=True)
            else:
                self.channel_selections[channel_name] = None
                await interaction.response.send_message(f"❌ {channel_name} channel cleared", ephemeral=True)

            # Auto-save configuration
            await self.auto_save_config()
        return channel_callback

    async def back_page(self, interaction: discord.Interaction):
        if self.page > 1:
            self.page -= 1
            self.setup_page_components()
            embed = self.cog.create_page_embed(self.page, self.total_pages, self.role_selections, self.channel_selections, self.settings, interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)

    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.total_pages:
            self.page += 1
            self.setup_page_components()
            embed = self.cog.create_page_embed(self.page, self.total_pages, self.role_selections, self.channel_selections, self.settings, interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)

    async def roster_cap_modal(self, interaction: discord.Interaction):
        class RosterCapModal(discord.ui.Modal):
            def __init__(self, view_ref):
                super().__init__(title="Set Roster Cap")
                self.view_ref = view_ref
                self.add_item(discord.ui.TextInput(
                    label="How many players per team?",
                    placeholder="53",
                    default=str(view_ref.settings["roster_cap"]),
                    required=True,
                    max_length=3
                ))

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    new_cap = int(self.children[0].value)
                    if new_cap < 1 or new_cap > 999:
                        await interaction.response.send_message("❌ Roster cap must be between 1 and 40.", ephemeral=True)
                        return
                    self.view_ref.settings["roster_cap"] = new_cap
                    await interaction.response.send_message(f"✅ Roster cap set to {new_cap} players per team.", ephemeral=True)

                    # Auto-save configuration
                    await self.view_ref.auto_save_config()

                    # Update the embed
                    embed = self.view_ref.cog.create_page_embed(self.view_ref.page, self.view_ref.total_pages, self.view_ref.role_selections, self.view_ref.channel_selections, self.view_ref.settings, interaction.guild)
                    await interaction.edit_original_response(embed=embed, view=self.view_ref)
                except ValueError:
                    await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)

        await interaction.response.send_modal(RosterCapModal(self))

    async def signings_mode_toggle(self, interaction: discord.Interaction):
        modes = ["offer", "sign", "both"]
        current_index = modes.index(self.settings["signings_mode"])
        next_index = (current_index + 1) % len(modes)
        self.settings["signings_mode"] = modes[next_index]

        # Auto-save configuration
        await self.auto_save_config()

        # Update button and embed
        self.setup_page_components()
        embed = self.cog.create_page_embed(self.page, self.total_pages, self.role_selections, self.channel_selections, self.settings, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    async def draft_toggle(self, interaction: discord.Interaction):
        self.settings["draft_enabled"] = not self.settings["draft_enabled"]

        # Auto-save configuration
        await self.auto_save_config()

        # Update button and embed
        self.setup_page_components()
        embed = self.cog.create_page_embed(self.page, self.total_pages, self.role_selections, self.channel_selections, self.settings, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    async def trade_deadline_modal(self, interaction: discord.Interaction):
        class TradeDeadlineModal(discord.ui.Modal):
            def __init__(self, view_ref):
                super().__init__(title="Set Trade Deadline")
                self.view_ref = view_ref
                self.add_item(discord.ui.TextInput(
                    label="Trade Deadline Date & Time",
                    placeholder="2024-12-31 23:59",
                    default=view_ref.settings["trade_deadline"],
                    required=True,
                    max_length=16
                ))

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    # Validate the datetime format
                    datetime.strptime(self.children[0].value, "%Y-%m-%d %H:%M")
                    self.view_ref.settings["trade_deadline"] = self.children[0].value
                    await interaction.response.send_message(f"✅ Trade deadline set to {self.children[0].value}. Trade commands will be disabled after this time.", ephemeral=True)

                    # Auto-save configuration
                    await self.view_ref.auto_save_config()

                    # Update the embed
                    embed = self.view_ref.cog.create_page_embed(self.view_ref.page, self.view_ref.total_pages, self.view_ref.role_selections, self.view_ref.channel_selections, self.view_ref.settings, interaction.guild)
                    await interaction.edit_original_response(embed=embed, view=self.view_ref)
                except ValueError:
                    await interaction.response.send_message("❌ Please enter a valid date format (YYYY-MM-DD HH:MM).", ephemeral=True)

        await interaction.response.send_modal(TradeDeadlineModal(self))

    async def close_setup(self, interaction: discord.Interaction):
        # Final auto-save to ensure everything is saved
        await self.auto_save_config()
        self.stop()

        embed = discord.Embed(
            title="✅ Setup Complete!",
            description="Your league settings have been automatically saved throughout the setup process.",
            color=discord.Color.green()
        )
        embed.add_field(name="Roster Cap", value=f"{self.settings['roster_cap']} players", inline=True)
        embed.add_field(name="Signings Mode", value=f"/{self.settings['signings_mode']}", inline=True)
        embed.add_field(name="Draft", value="Enabled" if self.settings['draft_enabled'] else "Disabled", inline=True)
        embed.add_field(name="Trade Deadline", value=self.settings['trade_deadline'], inline=False)
        embed.add_field(name="Free Agency Channel", value="✅ Configured" if self.channel_selections.get("Free Agency") else "❌ Not configured", inline=False)

        await interaction.response.edit_message(embed=embed, view=None)

async def setup(bot):
    await bot.add_cog(SetupCog(bot))