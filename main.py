import discord
import os
from discord import app_commands
from discord.ext import commands, tasks
import pymongo
from bson import ObjectId
from datetime import datetime, timedelta, timezone
import asyncio
import re
import traceback
import random

# =========================================
# ⚙️ CONFIGURATION
# =========================================

TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

DB_NAME = "enjoined_gaming_db"
ADMIN_IDS = [986251574982606888, 1458812527055212585]

# 📌 CHANNELS
CH_WELCOME = 1459444229255200971
CH_FIND_TEAM = 1459469475849175304
CH_VOUCH_LOG = 1459448284530610288
CH_WARNINGS = 1459448651704303667
CH_CODE_USE_LOG = 1459556690536960100
CAT_PRIVATE_ROOMS = 1459557142850830489

# Pricing
PRICES = {
    "text": {2: {1: 400, 2: 700, 4: 1200}, 3: {1: 500, 2: 900, 4: 1500}, 4: {1: 600, 2: 1100, 4: 1800}, 5: {1: 750, 2: 1300, 4: 2100}, 6: {1: 900, 2: 1500, 4: 2500}, 7: {1: 1050, 2: 1700, 4: 2800}},
    "voice": {2: {1: 500, 2: 900, 4: 1500}, 3: {1: 650, 2: 1100, 4: 1800}, 4: {1: 800, 2: 1400, 4: 2300}, 5: {1: 1000, 2: 1800, 4: 2900}, 6: {1: 1200, 2: 2100, 4: 3400}, 7: {1: 1400, 2: 2400, 4: 3900}}
}

EG_COND = """**EG cond:**\n• Respect everyone\n• Vouch after redeem\n• No abuse or spam\n• Follow admin instructions"""

# =========================================
# 🗄️ DATABASE
# =========================================

mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]

col_users = db["users"]
col_codes = db["codes"]
col_items = db["shop_items"]
col_vouch = db["vouch_pending"]
col_channels = db["active_channels"]
col_settings = db["settings"]
col_invites = db["invites_tracking"]
col_requests = db["pending_requests"]
col_giveaways = db["active_giveaways"]

if not col_settings.find_one({"_id": "config"}):
    col_settings.insert_one({"_id": "config", "panic": False, "locked": False})

# =========================================
# 🤖 BOT SETUP
# =========================================

class EGBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.invites = True
        super().__init__(command_prefix=".", intents=intents)
        self.invite_cache = {}

    async def setup_hook(self):
        self.check_vouch_timers.start()
        self.check_channel_expiry.start()
        self.check_invite_validation.start()
        self.check_request_timeouts.start()
        self.check_giveaways.start()
        await self.tree.sync()
        print("✅ Commands Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")
        for guild in self.guilds:
            try:
                invs = await guild.invites()
                self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invs}
            except: pass

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        error_msg = str(error)
        if isinstance(error, app_commands.CommandOnCooldown):
            error_msg = f"⏳ Cooldown: {error.retry_after:.2f}s"
        elif isinstance(error, app_commands.MissingPermissions):
            error_msg = "❌ You don't have permission."
        
        print(f"⚠️ Error: {error_msg}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"⚠️ Error: {error_msg}", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ Error: {error_msg}", ephemeral=True)

    # 🔄 TASKS
    @tasks.loop(seconds=30)
    async def check_vouch_timers(self):
        pending = col_vouch.find({})
        now = datetime.now(timezone.utc)
        warning_channel = self.get_channel(CH_WARNINGS)

        for p in pending:
            start_time = p["start_time"]
            if isinstance(start_time, str): start_time = datetime.fromisoformat(start_time)
            if start_time.tzinfo is None: start_time = start_time.replace(tzinfo=timezone.utc)
            
            elapsed = (now - start_time).total_seconds() / 60
            
            try: channel = self.get_channel(p["channel_id"])
            except: 
                col_vouch.delete_one({"_id": p["_id"]})
                continue

            user = self.get_guild(p.get("guild_id", 0)).get_member(p["user_id"]) if p.get("guild_id") else None

            if not channel:
                col_vouch.delete_one({"_id": p["_id"]})
                continue

            # 10 Min Reminder (Private Only)
            if elapsed >= 10 and not p.get("warned_10"):
                if user: 
                    await channel.send(f"⚠️ {user.mention} **Reminder:** 20 mins left to Vouch!\nFormat: `[{p['code_used']}] I got {p['service']}, thanks @admin`")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_10": True}})

            # 20 Min Warning (Private Only)
            elif elapsed >= 20 and not p.get("warned_20"):
                if user: 
                    await channel.send(f"🚨 {user.mention} **FINAL WARNING:** 10 mins left or channel will close.")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_20": True}})

            # 30 Min NO BAN - JUST CLOSE & LOG
            elif elapsed >= 30:
                if warning_channel and user:
                    embed = discord.Embed(title="⚠️ Failed to Vouch", description=f"{user.mention} did not vouch for **{p['service']}** in time.", color=discord.Color.orange())
                    await warning_channel.send(embed=embed)

                col_vouch.delete_one({"_id": p["_id"]})
                if channel: 
                    await channel.send("🔒 Time expired. Deleting channel...")
                    await asyncio.sleep(2)
                    await channel.delete(reason="Vouch time expired")

    @tasks.loop(minutes=1)
    async def check_giveaways(self):
        active = col_giveaways.find({})
        now = datetime.now(timezone.utc)
        for gw in active:
            end_time = gw["end_time"].replace(tzinfo=timezone.utc) if gw["end_time"].tzinfo is None else gw["end_time"]
            if now >= end_time:
                channel = self.get_channel(gw["channel_id"])
                if channel:
                    try:
                        msg = await channel.fetch_message(gw["message_id"])
                        guild = channel.guild
                        valid_users = [u for u in gw["entries"] if guild.get_member(u)]
                        if not valid_users: await msg.reply("❌ No valid entries.")
                        else:
                            winner = random.choice(valid_users)
                            await msg.reply(f"🎉 **WINNER:** <@{winner}>\nPrize: **{gw['prize']}**")
                            embed = msg.embeds[0]
                            embed.color = discord.Color.red()
                            embed.set_footer(text="Ended")
                            await msg.edit(embed=embed, view=None)
                    except: pass
                col_giveaways.delete_one({"_id": gw["_id"]})

    @tasks.loop(minutes=10)
    async def check_invite_validation(self):
        pending = col_invites.find({"valid": False})
        now = datetime.now(timezone.utc)
        for inv in pending:
            join_time = inv["joined_at"].replace(tzinfo=timezone.utc) if inv["joined_at"].tzinfo is None else inv["joined_at"]
            if now > (join_time + timedelta(hours=24)):
                col_invites.update_one({"_id": inv["_id"]}, {"$set": {"valid": True}})
                col_users.update_one({"_id": inv["inviter_id"]}, {"$inc": {"coins": 100, "invite_count": 1}})

    @tasks.loop(minutes=1)
    async def check_request_timeouts(self):
        reqs = col_requests.find({})
        now = datetime.now(timezone.utc)
        for r in reqs:
            expire_time = r["expires_at"].replace(tzinfo=timezone.utc) if r["expires_at"].tzinfo is None else r["expires_at"]
            if now > expire_time:
                col_users.update_one({"_id": r["host_id"]}, {"$inc": {"coins": r["price"]}})
                col_requests.delete_one({"_id": r["_id"]})
                try:
                    ch = self.get_channel(r["msg_channel_id"])
                    if ch:
                        msg = await ch.fetch_message(r["msg_id"])
                        await msg.edit(content=f"❌ **Request Expired.** Coins refunded to <@{r['host_id']}>.", view=None, embed=None)
                except: pass

    @tasks.loop(seconds=60)
    async def check_channel_expiry(self):
        # 1. Check Rented Private Channels
        active = col_channels.find({})
        now = datetime.now(timezone.utc)
        for c in active:
            end_time = c["end_time"].replace(tzinfo=timezone.utc) if c["end_time"].tzinfo is None else c["end_time"]
            if now > end_time:
                try:
                    channel = self.get_channel(c["channel_id"])
                    if channel: await channel.delete()
                except: pass
                col_users.update_one({"_id": c["owner_id"]}, {"$set": {"current_private_channel_id": None}})
                col_channels.delete_one({"_id": c["_id"]})
        
        # 2. Check Redeem/Buy Channels (Force delete after 30m if still exists)
        # Note: check_vouch_timers handles the logic, but this is a fail-safe
        pass # Vouch timer handles this logic explicitly

bot = EGBot()

def is_admin(user_id): return user_id in ADMIN_IDS

def get_user_data(user_id):
    data = col_users.find_one({"_id": user_id})
    if not data:
        data = {"_id": user_id, "coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None, "invite_count": 0}
        col_users.insert_one(data)
    if "invite_count" not in data:
        col_users.update_one({"_id": user_id}, {"$set": {"invite_count": 0}})
        data["invite_count"] = 0
    return data

# =========================================
# 🛍️ SHOP SYSTEM
# =========================================

@bot.tree.command(name="additem", description="Admin: Add item to shop")
async def additem(interaction: discord.Interaction, service: str, account_details: str, price: int):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    col_items.insert_one({"service": service, "details": account_details, "price": price, "added_at": datetime.now(timezone.utc)})
    await interaction.response.send_message(f"✅ Added **{service}** ({price} coins).", ephemeral=True)

@bot.tree.command(name="shop", description="View available items")
async def shop(interaction: discord.Interaction):
    await interaction.response.defer()
    pipeline = [{"$group": {"_id": "$service", "count": {"$sum": 1}, "price": {"$first": "$price"}}}]
    items = list(col_items.aggregate(pipeline))
    embed = discord.Embed(title="🛒 EG Coin Shop", description="Use `/buy [service]` to purchase.", color=discord.Color.green())
    if not items: embed.description = "🚫 Out of Stock"
    else:
        for item in items:
            embed.add_field(name=f"📦 {item['_id']}", value=f"💰 Price: **{item['price']}**\n📊 Stock: **{item['count']}**", inline=False)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="buy", description="Buy an item with coins")
async def buy(interaction: discord.Interaction, service: str):
    await interaction.response.defer(ephemeral=True)
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.followup.send("🔒 Shop Closed.")

    uid = interaction.user.id
    user_data = get_user_data(uid)
    item = col_items.find_one({"service": {"$regex": f"^{re.escape(service)}$", "$options": "i"}})
    if not item: return await interaction.followup.send(f"❌ **{service}** not found.")
    
    if user_data["coins"] < item["price"]: return await interaction.followup.send(f"❌ Need {item['price']} coins.")
    
    # REMOVED 24H COOLDOWN FOR BUYING

    col_items.delete_one({"_id": item["_id"]})
    col_users.update_one({"_id": uid}, {"$inc": {"coins": -item["price"]}, "$set": {"last_redeem": datetime.now(timezone.utc)}})
    
    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    for aid in ADMIN_IDS:
        m = guild.get_member(aid)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    chan = await guild.create_text_channel(f"buy-{interaction.user.name[:10]}", overwrites=overwrites)
    if bot.get_channel(CH_CODE_USE_LOG): await bot.get_channel(CH_CODE_USE_LOG).send(f"🛒 {interaction.user.mention} bought **{item['service']}**.")

    # INSERT VOUCH PENDING
    col_vouch.insert_one({
        "channel_id": chan.id, "guild_id": guild.id, "user_id": uid, 
        "code_used": item["price"], "service": item["service"], 
        "start_time": datetime.now(timezone.utc), "warned_10": False, "warned_20": False
    })

    embed = discord.Embed(title="🎁 Account Details", description="⏰ **Channel deletes in 30 mins.**", color=discord.Color.green())
    embed.add_field(name="Service", value=item['service'], inline=False)
    embed.add_field(name="ID", value=f"```\n{item['details'].split(' ')[0] if ' ' in item['details'] else 'See below'}\n```", inline=False)
    embed.add_field(name="Details/Pass", value=f"```\n{item['details']}\n```", inline=False)
    
    await chan.send(f"{interaction.user.mention}", embed=embed)
    await chan.send(f"📢 **VOUCH REQUIRED:** `{item['price']} I got {item['service']}, thanks @admin`")
    
    await interaction.followup.send(f"✅ Purchased! Check {chan.mention}")

# =========================================
# 🤝 INVITES
# =========================================

@bot.event
async def on_invite_create(invite):
    if invite.guild.id in bot.invite_cache:
        bot.invite_cache[invite.guild.id][invite.code] = invite.uses

@bot.event
async def on_invite_delete(invite):
    if invite.guild.id in bot.invite_cache and invite.code in bot.invite_cache[invite.guild.id]:
        del bot.invite_cache[invite.guild.id][invite.code]

@bot.event
async def on_member_join(member):
    c = bot.get_channel(CH_WELCOME)
    if c: await c.send(embed=discord.Embed(description=f"Welcome {member.mention}!\n\n{EG_COND}", color=discord.Color.purple()))
    role = discord.utils.get(member.guild.roles, name="Member")
    if role: await member.add_roles(role)

    guild_id = member.guild.id
    if guild_id not in bot.invite_cache: return
    old_invites = bot.invite_cache[guild_id]
    try: new_invites_obj = await member.guild.invites()
    except: return

    used_invite = None
    for inv in new_invites_obj:
        old_uses = old_invites.get(inv.code, 0)
        if inv.uses > old_uses:
            used_invite = inv
            break
    bot.invite_cache[guild_id] = {inv.code: inv.uses for inv in new_invites_obj}
    if used_invite: col_invites.insert_one({"user_id": member.id, "inviter_id": used_invite.inviter.id, "joined_at": datetime.now(timezone.utc), "valid": False})

@bot.event
async def on_member_remove(member):
    record = col_invites.find_one({"user_id": member.id})
    if record:
        if record["valid"]:
            col_users.update_one({"_id": record["inviter_id"], "coins": {"$gte": 100}}, {"$inc": {"coins": -100, "invite_count": -1}})
        col_invites.delete_one({"_id": record["_id"]})

    col_users.update_one({"_id": member.id}, {"$set": {"coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None, "invite_count": 0}})
    ch_data = col_channels.find_one({"owner_id": member.id})
    if ch_data:
        try:
            channel = member.guild.get_channel(ch_data["channel_id"])
            if channel: await channel.delete(reason="Owner left")
        except: pass
        col_channels.delete_one({"_id": ch_data["_id"]})

# =========================================
# 🔐 PRIVATE CHANNEL
# =========================================

class RequestView(discord.ui.View):
    def __init__(self, request_id, guest_ids):
        super().__init__(timeout=None)
        self.request_id = request_id
        self.guest_ids = guest_ids

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        req = col_requests.find_one({"_id": self.request_id})
        if not req: return await interaction.response.send_message("❌ Expired.", ephemeral=True)
        if interaction.user.id not in self.guest_ids: return await interaction.response.send_message("❌ Not invited.", ephemeral=True)

        await interaction.response.defer()
        col_requests.delete_one({"_id": self.request_id})
        
        guild = interaction.guild
        category = guild.get_channel(CAT_PRIVATE_ROOMS)
        host = guild.get_member(req["host_id"])
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
            host: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True)
        }

        try:
            if req["type"] == "text":
                chan = await guild.create_text_channel(req["name"], category=category, overwrites=overwrites)
            else:
                chan = await guild.create_voice_channel(req["name"], category=category, overwrites=overwrites)
            
            col_users.update_one({"_id": req["host_id"]}, {"$set": {"current_private_channel_id": chan.id}})
            col_channels.insert_one({"channel_id": chan.id, "owner_id": req["host_id"], "type": req["type"], "end_time": req["end_time"]})

            try: await interaction.message.edit(content=f"✅ **Created!** {chan.mention}\nAccepted by: {interaction.user.mention}", view=None, embed=None)
            except: pass
            await chan.send(f"{host.mention} {interaction.user.mention} Welcome!")
        except Exception as e: await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.guest_ids: return await interaction.response.send_message("❌ Not invited.", ephemeral=True)
        self.guest_ids.remove(interaction.user.id)
        await interaction.response.send_message("🚫 Declined.", ephemeral=True)

@bot.tree.command(name="makeprivatechannel", description="Request private channel")
@app_commands.choices(channel_type=[app_commands.Choice(name="Text", value="text"), app_commands.Choice(name="Voice", value="voice")], duration=[app_commands.Choice(name="1 Hour", value=1), app_commands.Choice(name="2 Hours", value=2), app_commands.Choice(name="4 Hours", value=4)])
@app_commands.describe(members="Mention users (Required)")
async def makeprivate(interaction: discord.Interaction, channel_type: str, name: str, duration: int, members: str):
    await interaction.response.defer(ephemeral=False)
    try:
        config = col_settings.find_one({"_id": "config"})
        if config["panic"] and not is_admin(interaction.user.id): return await interaction.followup.send("🔒 Maintenance.")

        uid = interaction.user.id
        data = get_user_data(uid)
        if data.get("current_private_channel_id") and not is_admin(uid): return await interaction.followup.send("❌ You already have a channel.")

        guests = [int(id) for id in re.findall(r'<@!?(\d+)>', members)]
        guests = list(set(guests))
        if uid in guests: guests.remove(uid)
        
        if not guests: return await interaction.followup.send("❌ Mention at least 1 guest.")
        total = len(guests) + 1
        if total > 7: return await interaction.followup.send("❌ Max 7 users.")

        try: price = PRICES[channel_type][total][duration]
        except KeyError: return await interaction.followup.send("❌ Pricing Error.")

        if data["coins"] < price: return await interaction.followup.send(f"❌ Need {price} coins.")

        col_users.update_one({"_id": uid}, {"$inc": {"coins": -price}})
        req_id = ObjectId()
        
        embed = discord.Embed(title=f"🔒 {channel_type.title()} Room Request", description=f"{interaction.user.mention} wants a room.\n**Guests:** {' '.join([f'<@{g}>' for g in guests])}\n**Price:** {price}\n**Duration:** {duration}h", color=discord.Color.gold())
        msg = await interaction.followup.send(embed=embed, view=RequestView(req_id, guests))
        col_requests.insert_one({"_id": req_id, "host_id": uid, "guests": guests, "type": channel_type, "name": name, "price": price, "end_time": datetime.now(timezone.utc) + timedelta(hours=duration), "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5), "msg_id": msg.id, "msg_channel_id": interaction.channel.id})
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected Error: {e}")

# =========================================
# 💰 UTILS
# =========================================

class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.primary, custom_id="join_giveaway")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        col_giveaways.update_one({"_id": self.giveaway_id}, {"$push": {"entries": interaction.user.id}})
        await interaction.response.send_message("✅ Entry Confirmed!", ephemeral=True)

@bot.tree.command(name="giveaway", description="Admin: Start giveaway")
@app_commands.checks.cooldown(1, 300)
async def giveaway(interaction: discord.Interaction, minutes: int, prize: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    end_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    embed = discord.Embed(title="🎉 GIVEAWAY!", description=f"**Prize:** {prize}\n**Ends:** <t:{int(end_time.timestamp())}:R>", color=discord.Color.magenta())
    gw_id = ObjectId()
    await interaction.response.send_message(embed=embed, view=GiveawayView(gw_id))
    msg = await interaction.original_response()
    col_giveaways.insert_one({"_id": gw_id, "channel_id": interaction.channel.id, "message_id": msg.id, "prize": prize, "end_time": end_time, "entries": []})

@bot.tree.command(name="daily", description="Claim coins")
async def daily(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = interaction.user.id
    d = get_user_data(uid)
    now = datetime.now(timezone.utc)
    if d.get("daily_cd") and not is_admin(uid):
        daily_cd = d["daily_cd"].replace(tzinfo=timezone.utc) if d["daily_cd"].tzinfo is None else d["daily_cd"]
        if now < daily_cd: return await interaction.followup.send(f"⏳ Come back in {int((daily_cd - now).total_seconds()//3600)}h.")
    col_users.update_one({"_id": uid}, {"$inc": {"coins": 100}, "$set": {"daily_cd": now + timedelta(hours=24)}})
    await interaction.followup.send(f"💰 +100 Coins!")

@bot.tree.command(name="redeem", description="Redeem code")
async def redeem(interaction: discord.Interaction, code: str):
    await interaction.response.defer(ephemeral=True)
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.followup.send("🔒 Maintenance.")
    
    uid = interaction.user.id
    d = get_user_data(uid)
    
    # REMOVED 24H COOLDOWN FOR REDEEM
    
    cd = col_codes.find_one({"code": code})
    if not cd: return await interaction.followup.send("❌ Invalid Code.")
    
    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    for aid in ADMIN_IDS:
        m = guild.get_member(aid)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    col_codes.delete_one({"code": code})
    chan = await guild.create_text_channel(f"redeem-{interaction.user.name[:10]}", overwrites=overwrites)
    col_users.update_one({"_id": uid}, {"$set": {"last_redeem": datetime.now(timezone.utc)}})
    
    if bot.get_channel(CH_CODE_USE_LOG): await bot.get_channel(CH_CODE_USE_LOG).send(f"`{code}` used by {interaction.user.mention}")

    col_vouch.insert_one({"channel_id": chan.id, "guild_id": guild.id, "user_id": uid, "code_used": code, "service": cd['service'], "start_time": datetime.now(timezone.utc), "warned_10": False, "warned_20": False})
    
    # 🎨 EXACT EMBED MATCH
    embed = discord.Embed(title="🎁 Account Details", description="⏰ **Channel deletes in 30 mins.**", color=discord.Color.green())
    embed.add_field(name="Service", value=cd['service'], inline=False)
    embed.add_field(name="ID", value=f"```\n{cd['email']}\n```", inline=False)
    embed.add_field(name="Pass", value=f"```\n{cd['password']}\n```", inline=False)
    
    await chan.send(f"{interaction.user.mention}", embed=embed)
    await chan.send(f"📢 **VOUCH REQUIRED:** `{code} I got {cd['service']}, thanks @admin`")
    await interaction.followup.send(f"✅ Created: {chan.mention}")

@bot.tree.command(name="invites", description="Show stats")
async def invites(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    pending = col_invites.count_documents({"inviter_id": interaction.user.id, "valid": False})
    await interaction.response.send_message(f"📩 **Invites:** {d.get('invite_count', 0)} Valid | {pending} Pending", ephemeral=True)

@bot.tree.command(name="lock", description="Admin: Lock")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    if "redeem-" in interaction.channel.name or "buy-" in interaction.channel.name: return await interaction.response.send_message("❌ Cannot lock Redeem channels.", ephemeral=True)
    if col_channels.find_one({"channel_id": interaction.channel.id}): return await interaction.response.send_message("❌ Cannot lock Private channels.", ephemeral=True)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    role = discord.utils.get(interaction.guild.roles, name="Member")
    if role: await interaction.channel.set_permissions(role, send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": True}})
    await interaction.response.send_message("🔒 Locked.")

@bot.tree.command(name="unlock", description="Admin: Unlock")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None, send_messages_in_threads=None, create_public_threads=None, create_private_threads=None)
    role = discord.utils.get(interaction.guild.roles, name="Member")
    if role: await interaction.channel.set_permissions(role, send_messages=None, send_messages_in_threads=None, create_public_threads=None, create_private_threads=None)
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": False}})
    await interaction.response.send_message("🔓 Unlocked.")

@bot.tree.command(name="addcoins", description="Admin: Add coins to user")
async def addcoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    get_user_data(user.id)
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"✅ Added {amount} to {user.mention}", ephemeral=True)

@bot.tree.command(name="warn", description="Admin: Warn a user")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    try: await user.send(f"⚠️ **Warned in {interaction.guild.name}**\nReason: {reason}")
    except: pass
    warn_channel = bot.get_channel(CH_WARNINGS)
    if warn_channel:
        embed = discord.Embed(title="⚠️ User Warned", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=True)
        embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await warn_channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Warned {user.mention}.", ephemeral=True)

@bot.tree.command(name="addcode", description="Admin: Add code")
async def addcode(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    if col_codes.find_one({"code": code}): return await interaction.response.send_message("❌ Code exists.", ephemeral=True)
    col_codes.insert_one({"code": code, "service": service, "email": email, "password": password})
    await interaction.response.send_message(f"✅ Added `{code}`", ephemeral=True)

@bot.tree.command(name="deletecode", description="Admin: Delete code")
async def deletecode(interaction: discord.Interaction, code: str):
    if not is_admin(interaction.user.id): return
    res = col_codes.delete_one({"code": code})
    if res.deleted_count > 0: await interaction.response.send_message(f"🗑️ Deleted", ephemeral=True)
    else: await interaction.response.send_message("❌ Not found", ephemeral=True)

@bot.tree.command(name="seecodes", description="Admin: See codes/items")
async def seecodes(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    items = list(col_items.find({}))
    if not items: return await interaction.response.send_message("Empty.", ephemeral=True)
    embed = discord.Embed(title="📂 Shop Items", color=discord.Color.blue())
    desc = ""
    for c in items:
        desc += f"• **{c['service']}** | {c['price']} Coins\n"
        if len(desc) > 3500: break
    embed.description = desc
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clear", description="Admin: Clear")
async def clear(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction.user.id): return
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=min(amount, 100))
    await interaction.followup.send("🧹 Done", ephemeral=True)

@bot.tree.command(name="panic", description="Admin: Panic")
async def panic(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    c = col_settings.find_one({"_id": "config"})
    col_settings.update_one({"_id": "config"}, {"$set": {"panic": not c["panic"]}})
    await interaction.response.send_message(f"🚨 Panic: {not c['panic']}", ephemeral=True)

@bot.tree.command(name="findteam", description="Find Team")
async def findteam(interaction: discord.Interaction, role: str, level: str, message: str):
    if interaction.channel.id != CH_FIND_TEAM: return await interaction.response.send_message("❌ Wrong channel.", ephemeral=True)
    embed = discord.Embed(title="🎮 Team Request", color=discord.Color.orange())
    embed.add_field(name="User", value=interaction.user.mention)
    embed.add_field(name="Info", value=f"{role} | {level}\n{message}")
    await interaction.response.send_message(embed=embed, delete_after=1800)

@bot.tree.command(name="leaderboard", description="Top users")
@app_commands.choices(category=[app_commands.Choice(name="Coins", value="coins"), app_commands.Choice(name="Invites", value="invite_count")])
async def leaderboard(interaction: discord.Interaction, category: str):
    await interaction.response.defer()
    top = col_users.find().sort(category, -1).limit(10)
    embed = discord.Embed(title=f"🏆 Top 10 {category.title()}", color=discord.Color.gold())
    text = ""
    for idx, u in enumerate(top, 1): text += f"**{idx}.** <@{u['_id']}> • **{u.get(category, 0)}**\n"
    embed.description = text if text else "No data."
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="status", description="Balance")
async def status(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💳 {d['coins']} Coins", ephemeral=True)

@bot.tree.command(name="pay", description="Pay coins")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    if amount <= 0 or amount > 1000000: return await interaction.response.send_message("❌ Invalid.", ephemeral=True)
    if interaction.user.id == user.id: return await interaction.response.send_message("❌ No.", ephemeral=True)
    s = get_user_data(interaction.user.id)
    if s["coins"] < amount: return await interaction.response.send_message("❌ Low balance.", ephemeral=True)
    get_user_data(user.id)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -amount}})
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"💸 Paid {amount} to {user.mention}", ephemeral=False)

@bot.tree.command(name="help", description="Show commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="EG BOT", color=discord.Color.blue())
    embed.add_field(name="💰", value="`/daily`\n`/status`\n`/pay`", inline=True)
    embed.add_field(name="🛒", value="`/shop`\n`/buy`", inline=True)
    embed.add_field(name="🎁", value="`/redeem`\n`/makeprivatechannel`", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Admin: Panel")
async def ticketpanel(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    class TV(discord.ui.View):
        def __init__(self): super().__init__(timeout=None)
        @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green, custom_id="tic")
        async def op(self, intr, b):
            ow = {intr.guild.default_role: discord.PermissionOverwrite(read_messages=False), intr.user: discord.PermissionOverwrite(read_messages=True, send_messages=True), intr.guild.me: discord.PermissionOverwrite(read_messages=True)}
            for a in ADMIN_IDS:
                m = intr.guild.get_member(a)
                if m: ow[m] = discord.PermissionOverwrite(read_messages=True)
            c = await intr.guild.create_text_channel(f"ticket-{intr.user.name}", overwrites=ow, topic=f"Ticket Owner: {intr.user.id}")
            await c.send(f"{intr.user.mention} Support here. `/close`", view=None)
            await intr.response.send_message(f"✅ {c.mention}", ephemeral=True)
    await interaction.channel.send("📩 **Support**", view=TV())
    await interaction.response.send_message("Done", ephemeral=True)

@bot.tree.command(name="close", description="Close ticket")
async def close(interaction: discord.Interaction):
    if "ticket-" not in interaction.channel.name and "redeem-" not in interaction.channel.name: return
    is_owner = interaction.channel.topic and f"Ticket Owner: {interaction.user.id}" in interaction.channel.topic
    if is_admin(interaction.user.id) or is_owner or "redeem-" in interaction.channel.name:
        await interaction.response.send_message("👋 Closing...")
        await asyncio.sleep(3)
        await interaction.channel.delete()

@bot.tree.command(name="ann", description="Admin: Announce")
async def ann(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not is_admin(interaction.user.id): return
    await channel.send(embed=discord.Embed(title=title, description=message, color=discord.Color.blue()))
    await interaction.response.send_message("✅ Sent", ephemeral=True)

@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id == CH_FIND_TEAM:
        if not is_admin(message.author.id): await message.delete()
        return
    pending = col_vouch.find_one({"channel_id": message.channel.id, "user_id": message.author.id})
    if pending:
        if re.match(r"^\[.+\]\s+i got\s+.+,\s*thanks\s+(@admin|<@!?\d+>|<@&\d+>)$", message.content, re.IGNORECASE):
            await message.add_reaction("✅")
            col_vouch.delete_one({"_id": pending["_id"]})
            if bot.get_channel(CH_VOUCH_LOG): await bot.get_channel(CH_VOUCH_LOG).send(f"✅ {message.author.name} vouched for `{pending['service']}`")
            # Force close after vouch
            await asyncio.sleep(5)
            await message.channel.delete()
        else:
            await message.delete()
            await message.channel.send("❌ Format: `[CODE] I got SERVICE, thanks @admin`", delete_after=5)
    await bot.process_commands(message)

bot.run(TOKEN)
