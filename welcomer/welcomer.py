import asyncio
from copy import deepcopy
import json
import logging
from random import choice as rand_choice
import importlib

import clashroyale
import discord
import json
import datetime
from redbot.core import commands, checks, Config
from redbot.core.data_manager import bundled_data_path, cog_data_path

from .menus.helper import Letter, Symbol

credits = "Bot by Threat Level Gaming"
creditIcon = "https://cdn.discordapp.com/attachments/718649031009501285/772704601384157184/image0.png"

log = logging.getLogger("red.cogs.welcomer")

class Welcomer(commands.Cog):
    """Commands for Clash Royale Family Management"""

    def __init__(self, bot):
        self.bot = bot
        self.tags = self.bot.get_cog('ClashRoyaleTools').tags
        self.constants = self.bot.get_cog('ClashRoyaleTools').constants
        self.clans = self.bot.get_cog('ClashRoyaleClans')
        self.user_history = {}
        self.joined = {}
        self.config = Config.get_conf(self, identifier=251098479837495659987)
        default_global = {
            "module": "ThreatLevelMenu",
            "enabled": False
        }
        self.config.register_global(**default_global)
        default_guild = {}
        self.config.register_guild(**default_guild)
        self.welcome_path = str(bundled_data_path(self.clans) / "welcome_messages.json")
        with open(self.welcome_path) as file:
            self.welcome = dict(json.load(file))
        self.menu = {}

    def embed(self, **kwargs):
        credits = "Bot by Threat Level Gaming"
        creditIcon = "https://cdn.discordapp.com/attachments/718649031009501285/772704601384157184/image0.png"
        return discord.Embed(**kwargs).set_footer(
            text=credits,
            icon_url=creditIcon
        )

    async def load_menu_module(self):
        config_menu = await self.config.module()
        module = importlib.import_module(".menus." + config_menu.lower(), package = 'welcomer')

        class_ = getattr(module, config_menu)
        instance = class_(self)

        self.menu = instance.menu

    async def crtoken(self):
        # Clash Royale API
        token = await self.bot.get_shared_api_tokens("clashroyale")
        if token['token'] is None:
            log.error("CR Token is not SET. Use !set api clashroyale token,YOUR_TOKEN to set it")
        self.clash = clashroyale.official_api.Client(token=token['token'],
                                                  is_async=True,
                                                  url="https://proxy.royaleapi.dev/v1")

    async def emoji(self, name):
        """Emoji by name."""
        for emoji in self.bot.emojis:
            if emoji.name == name.replace(" ", "").replace("-", "").replace(".", ""):
                return '<:{}:{}>'.format(emoji.name, emoji.id)
        return ''

    async def change_message(self, user:discord.Member, new_embed, reactions:list = None):
        channel = user.dm_channel
        if channel is None:
            channel = await user.create_dm()

        async for message in channel.history(limit=10):
            if message.author.id == self.bot.user.id:
                try:
                    """ Skip messages older than 2 days, if you try to delete messages older than 2 weeks
                        you can be rate limited for errors.
                    """
                    if not message.created_at > datetime.datetime.today() - datetime.timedelta(days=2):
                        continue
                    await message.delete()
                except discord.NotFound:
                    pass

        retry = 0
        try:
            new_message = await channel.send(embed=new_embed)
        except discord.Forbidden:
            return await self.logger(user)

        while retry < 10:
            try:
                reaction_added = []
                for reaction in reactions:
                    current_reaction = reaction
                    if reaction not in reaction_added:
                        await new_message.add_reaction(reaction)
                        reaction_added.append(reaction)
                if len(reaction_added) == len(reactions):
                    break
            except discord.Forbidden:
                return await self.logger(user)
            except discord.errors.NotFound:
                retry += 1

        return new_message.id

    async def ReactionAddedHandler(self, reaction: discord.Reaction, user: discord.Member, history, data):
        menu = self.menu.get(history[-1])
        if(Symbol.arrow_backward == reaction.emoji):       # if back button then just load previous
            history.pop()
            await self.load_menu(user, history[-1])
            return

        for option in menu.get("options"):      # do the corresponding reaction
            emoji = option.get('emoji')
            if emoji == str(reaction.emoji):
                if "track" in menu:
                    data[history[-1]] = option.get('name')
                if "menu" in option.get('execute'):
                    history.append(option.get('execute').get("menu"))
                    await self.load_menu(user, option.get('execute').get("menu"))
                if "function" in option.get('execute'):       # if it is executable
                    method = getattr(self, option.get('execute').get("function"))
                    await method(user)
                return

    async def load_menu(self, user: discord.Member, menu: str):
        log.error(f"Loading Menu {menu} for {user}")
        menu = self.menu.get(menu)
        message = ""
        reactions = []

        embed = deepcopy(menu.get("embed"))
        embed.description = embed.description.format(user)

        if "thumbnail" in menu:
            embed.set_thumbnail(url=menu.get("thumbnail"))

        if "image" in menu:
            embed.set_image(url=menu.get("image"))

        if "dynamic_options" in menu:
            method = getattr(self, menu.get("dynamic_options"))
            menu["options"] = await method(user)

        if "options" in menu:
            for option in menu.get("options"):
                emoji = option.get('emoji')
                reactions.append(emoji.replace(">", "").replace("<", ""))
                message += f"{emoji} "
                message += option.get('name')
                message += "\r\n"

        if menu.get("go_back"):
            message += "\r\n"
            message += f":arrow_backward: "
            message += "Go back"
            message += "\r\n"
            reactions.append(Symbol.arrow_backward)

        if "options" in menu:
            if "hide_options" not in menu:
                name = "Options"
                if embed.fields and embed.fields[-1].name == name:
                    embed.set_field_at(len(embed.fields) - 1, name=name, value=message)
                else:
                    embed.add_field(name=name, value=message)

        if "finished" in menu:
            await self.logger(user)

        new_message = await self.change_message(user, embed, reactions=reactions)

        return new_message

    async def _add_roles(self, member, role_names):
        log.error(f"Assigning roles to {member}: {role_names}")
        """Add roles"""
        guild = self.bot.get_guild(await self.config.server_id())
        roles = [discord.utils.get(guild.roles, name=role_name) for role_name in role_names]
        log.error(f"Adding roles to {member}: {roles}")
        if any([x is None for x in roles]):
            raise RuntimeError("A role wasn't found for {member} in {role_names} [{roles}]")
        try:
            await guild.get_member(member.id).add_roles(*roles)
        except discord.Forbidden:
            raise
        except discord.HTTPException:
            raise

    async def errorer(self, member: discord.Member):
        menu_name = "choose_path"
        await self.load_menu(member, menu_name)
        self.user_history[member.id]["history"].append(menu_name)

    async def guest(self, member: discord.Member):
        """Add guest role and change nickname to CR"""
        log.error(f"Running guest for {member}")
        guild = self.bot.get_guild(await self.config.server_id())
        member = guild.get_member(member.id)
        role_names = []
        if not member:
            log.error(f"{member} not found in the server.")
            return self.errorer(member)
        try:
            profiletag = self.tags.getTag(member.id, 1)
            if profiletag is None:
                log.error(f"{member} couldn't find a tag.")
                return await self.errorer(member)
            profiledata = await self.clash.get_player(profiletag)
            ign = profiledata.name
            role_names.append("Clash Royale")
        except clashroyale.RequestError as err:
            log.error(f"{member} couldn't get profiledata: {err}")
            return await self.errorer(member)

        role_names.append("Community")
        await self._add_roles(member, role_names);

        menu_name = "end_guest"
        await self.load_menu(member, menu_name)
        self.user_history[member.id]["history"].append(menu_name)

    async def verify_membership(self, member:discord.Member):
        guild = self.bot.get_guild(await self.config.server_id())
        member = guild.get_member(member.id)
        membership = False
        clans_joined = []
        role_names = []
        ign = None
        try:
            player_tags = self.tags.getAllTags(member.id)
            for tag in player_tags:
                player_data = await self.clash.get_player(tag)
                if player_data.clan is None:
                    clantag = ""
                else:
                    clantag = player_data.clan.tag.strip("#")
                for name, data in self.clans.family_clans.items():
                    if data.get("tag") == clantag:
                        membership = True
                        clans_joined.append(data.get("name"))
                        role_names.append(data.get("clanrole"))
                        break
                if ign is None:
                    ign = player_data.name
        except clashroyale.RequestError as err: 
            log.error(f"Verify Memebership Error: {err}")
            return await self.errorer(member)
        log.error(f"Membership: {membership}")
        if membership:
            try:
                new_name = ign
                newclanname = " | ".join(clans_joined)
                newname = ign + " | " + newclanname
                await member.edit(nick=newname)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except (AttributeError):
                log.error("Cannot change the nickname of a server owner.")
                pass

            role_names.append("Clash Royale")
            role_names.append('Community')

            await self._add_roles(member, role_names)
        else:
            return await self.errorer(member)

        menu_name = "give_tags"
        await self.load_menu(member, menu_name)
        self.user_history[member.id]["history"].append(menu_name)

        welcomeMsg = rand_choice(self.welcome["GREETING"])
        channel = self.bot.get_channel(await self.config.global_channel_id())
        await channel.send(welcomeMsg.format(member))

    async def clans_options(self, user):
        clandata = []
        options = []
        for clankey, data in self.clans.family_clans.items():
            try:
                clan = await self.clans.get_clandata_by_tag(data.get('tag'))
                if (clan is None):
                    log.error(f"Error loading tag {data.get('tag')}")
                    continue

                clandata.append(clan)
            except clashroyale.RequestError:
                return await user.dm_channel.send("Error: cannot reach Clash Royale Servers. Please try again later.")

        clandata = sorted(clandata, key=lambda x: (x["required_trophies"], x["clan_score"]), reverse=True)

        index = 0
        for clan in clandata:
            clankey = clan["name"]

            member_count = clan.get("members")
            if member_count < 50:
                showMembers = str(member_count) + "/50"
            else:
                showMembers = "**FULL**"

            title = "[{}] {} ({}+) ".format(showMembers, clan["name"], clan["required_trophies"])

            options.append({
                "name": title,
                "emoji": Letter.alphabet[index],
                "execute": {
                    "menu": "end_member"
                }
            })

            index += 1

        options.append({
            "name": "I am not sure, I want to talk to a human.",
            "emoji": Letter.alphabet[index],
            "execute": {
                "menu": "end_human"
            }
        })

        return options

    async def logger(self, user):
        """Log into a channel"""
        channel = self.bot.get_channel(await self.config.log_channel_id())

        embed = discord.Embed(color=discord.Color.green(), description="User Joined")
        avatar = user.avatar_url if user.avatar else user.default_avatar_url
        embed.set_author(name=user.name, icon_url=avatar)

        try:
            data = self.user_history[user.id]["data"] 
        except KeyError:
            return await channel.send(embed=embed)

        if "choose_path" in data:
            path_map = {
                "I am just visiting.": "Visitor Joined",
                "I want to join a clan.": "Recruit Joined",
                "I am already in one of your clans.": "Member Joined",
            }
            embed.description = path_map[data["choose_path"]]

        if "name" in data:
            embed.add_field(name="Player:", value="{} {} ({})".format(data["emoji"],
                                                                      data["name"],
                                                                      data["tag"]), inline=False)

        if "clan" in data:
            embed.add_field(name="Current clan:", value=data["clan"], inline=False)

        if "academy_coaching" in data:
            if data["academy_coaching"] != "Not interested.":
                embed.add_field(name="Coaching:", value=data["academy_coaching"], inline=False)

        if "join_clan" in data:
            if data["join_clan"] != "I am not sure, I want to talk to a human.":
                embed.add_field(name="Clan Preference:", value=data["join_clan"], inline=False)

        if "refferal_menu" in data:
            if data["refferal_menu"] != "Other":
                embed.add_field(name="Invited from:", value=data["refferal_menu"], inline=False)

        if "location_menu" in data:
            embed.add_field(name="Region:", value=data["location_menu"], inline=False)

        if "age_menu" in data:
            if data["age_menu"] != "Prefer Not to Answer":
                embed.add_field(name="Age:", value=data["age_menu"], inline=False)

        await channel.send(embed=embed)

    async def launch_menu(self, member:discord.Member):
        guild = member.guild
        # Allow command to be run in legend server. Use list so test servers can be added
        if guild.id != await self.config.server_id():
            return
        self.joined[member.id] = member

        await self.load_menu(member, "main")

        if member.id in self.user_history:
            del self.user_history[member.id]

        await asyncio.sleep(1200)

        if member.id in self.user_history:
            return

        if member in guild.members:
            menu_name = "leave_alone"
            await self.load_menu(member, menu_name)
            self.user_history[member.id] = {"history": ["main", menu_name], "data": {}}

    @commands.Cog.listener()
    async def on_member_join(self, member:discord.Member):
        log.error(f"Member joined: {member}")
        if await self.config.enabled():
            await self.launch_menu(member)


    @commands.Cog.listener()
    async def on_member_remove(self, member:discord.Member):
        guild = member.guild
        if guild.id != await self.config.server_id():
            return

        embed = discord.Embed(color=discord.Color.red(), description="User Left")
        avatar = member.avatar_url if member.avatar else member.default_avatar_url
        embed.set_author(name=member.display_name, icon_url=avatar)
        channel = self.bot.get_channel(await self.config.log_channel_id())
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Member):
        guild = self.bot.get_guild(await self.config.server_id())
        member = guild.get_member(user.id)
        if reaction.message.channel.type is discord.ChannelType.private and self.bot.user.id != member.id:
            if member.id not in self.joined:
                return
            history = {"history": ["main"], "data": {}}
            if member.id in self.user_history:
                history = self.user_history[member.id]
            else:
                self.user_history.update({member.id: history})

            await self.ReactionAddedHandler(reaction, member, history["history"], history["data"])


    @commands.group(name='welcomer')
    async def _welcomer(self, ctx):
        """Welcome Command Group"""

    @_welcomer.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def menu(self, ctx, user:discord.Member = None):
        """Send the welcome message to yourself or optionally
        another user.

        For example: `[p]weclome menu [user]
        """
        if user is None:
            user = ctx.message.author
        await self.launch_menu(user)

    @_welcomer.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)    
    async def verify(self, ctx, user:discord.Member = None):
        """Runs the verify membership function. Debug only.

        For example: `[p]weclome verify [user]
        """
        if user is None:
            user = ctx.message.author
        await self.verify_membership(user)


    @_welcomer.command(name="server")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def server(self, ctx, server_id = None):
        """Set the discord server id this is enabled for.

        For example: `[p]weclome server {serverid}
        """
        if server_id is None:
            await ctx.send(f"Server ID set to {await self.config.server_id()}")
            return
        await self.config.server_id.set(int(server_id))
        await ctx.send("Server ID set.")

    @_welcomer.command(name="enable")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def enable(self, ctx):
        """Enables the on_member_join callback.

        For example: `[p]weclome enable
        """
        await self.config.enabled.set(True)
        await ctx.send("Welcome cog enabled.")

    @_welcomer.command(name="disable")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def disable(self, ctx):
        """Disables the on_member_join callback.

        For example: `[p]weclome disable
        """
        await self.config.enabled.set(False)
        await ctx.send("Welcome cog disabled.")

    @_welcomer.command(name="log")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def logchannel(self, ctx, channel:discord.TextChannel = None):
        """Set or print the log channel id.

        For example: `[p]weclome server {channelid}
        """
        if channel is None:
            guild_channel = discord.utils.get(self.bot.get_all_channels(), id=(await self.config.log_channel_id()))
            await ctx.send(f"Log channel is current set to {guild_channel.mention}", allowed_mentions=discord.AllowedMentions.all())
            return
        await self.config.log_channel_id.set(channel.id)
        await ctx.send("Log channel set.")

    @_welcomer.command(name="global")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def globalchannel(self, ctx, channel:discord.TextChannel):
        """Set or print the global channel id.

        For example: `[p]weclome server {channelid}
        """
        if channel is None:
            await ctx.send(f"Global channel is currently set to {await self.config.global_channel_id()}")
            return
        await self.config.global_channel_id.set(channel.id)
        await ctx.send("Global channel set.")

    @_welcomer.command(name="module")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def module(self, ctx, module:str = None):
        """ load a welcome module Example:
            [p]welcome module legendmenu
        """
        if module is None:
            await ctx.send(f"Module is currently set to {await self.config.module()}")
            return
        await self.config.module.set(module)
        await ctx.send("Module set.")
        await self.load_menu_module()

    @_welcomer.command(name="jump")
    async def jump(self, ctx, menu_name:str):
        await self.load_menu(ctx.message.author, menu_name)
        self.joined[ctx.message.author.id] = ctx.message.author
        if (ctx.message.author.id not in self.user_history):
            self.user_history[ctx.message.author.id] = {"history": ["main", menu_name], "data": {}}
        else:
            self.user_history[ctx.message.author.id]["history"].append(menu_name)

    @commands.command()
    async def savetag(self, ctx, profiletag: str):
        """ save your Clash Royale Profile Tag
        Example:
            [p]savetag #CRRYRPCC
        """
        member = ctx.author

        if ctx.message.channel.type is not discord.ChannelType.private:
            return

        profiletag = self.tags.formatTag(profiletag)

        if not self.tags.verifyTag(profiletag):
            return await ctx.send("The ID you provided has invalid characters. Please try again.")

        try:
            profiledata = await self.clash.get_player(profiletag)
            name = profiledata.name

            if profiledata.clan is not None:
                self.user_history[member.id]["data"]["clan"] = profiledata.clan.name

            self.user_history[member.id]["data"]["name"] = name
            self.user_history[member.id]["data"]["tag"] = profiledata.tag
            self.user_history[member.id]["data"]["emoji"] = await self.emoji(profiledata.arena.name.replace(' ', '').lower())

            await self.tags.saveTag(member.id, profiletag)

            menu_name = "choose_path"
            await self.load_menu(member, menu_name)
            self.user_history[member.id]["history"].append(menu_name)

        except clashroyale.NotFoundError:
            return await ctx.send("We cannot find your ID in our database, please try again.")
        except clashroyale.RequestError:
            return await ctx.send("Error: cannot reach Clash Royale Servers. Please try again later.")
        except:
            menu_name = "choose_path"
            await self.load_menu(member, menu_name)
            self.user_history[member.id]["history"].append(menu_name)