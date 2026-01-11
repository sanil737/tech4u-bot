import discord
import os
from discord import app_commands
from discord.ext import commands, tasks
import pymongo
from datetime import datetime, timedelta
import asyncio
import re

# =========================================
# ⚙️ CONFIGURATION & CONSTANTS
# =========================================

TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

DB_NAME = "enjoined_gaming_db"
ADMIN_IDS = [986251574982606888, 1458812527055212585]

# 📌 CHANNEL & CATEGORY IDS
CH_WELCOME = 1459444229255200971
CH_FIND_TEAM = 1459469475849175304
CH_VOUCH_LOG = 1459448284530610288
CH_WARNINGS = 1459448651704303667
CH_CODE_USE_LOG = 1459556690536960100  # <--- NEW LOG CHANNEL
CAT_PRIVATE_ROOMS = 1459557142850830489

# Pricing
PRICES = {
    "text": {
        2: {1: 400, 2: 700, 4: 1200},
        3: {1: 500, 2: 900, 4: 1500},
        4: {1: 600, 2: 1100, 4: 1800},
        5: {1: 750, 2: 1300, 4: 2100},
        6: {1: 900, 2: 1500, 4: 2500},
        7: {1: 1050, 2: 1700, 4: 2800},
    },
    "voice": {
        2: {1: 500, 2: 900, 4: 1500},
        3: {1: 650, 2: 1100, 4: 1800},
        4: {1: 800, 2: 1400, 4: 2300},
        5: {1: 1000, 2: 1800, 4: 2900},
        6: {1: 1200, 2: 2100, 4: 3400},
        7: {1: 1400, 2: 2400, 4: 3900},
    }
}

EG_COND = """**EG cond:**
• Respect everyone
• Vouch after redeem
• No abuse or spam
• Follow admin instructions"""

# =========================================
# 🗄️ DATABASE SETUP
# =========================================

mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]

col_users = db["users"]           
col_codes = db["codes"]           
col_vouch = db["vouch_pending"]   
col_channels = db["active_channels"] 
col_settings = db["settings"]
col_invites = db["invites_tracking"] 
col_requests = db["pending_requests"] 

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
        await self.tree.sync() 
        print("✅ Commands Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")
        for guild in self.guilds:
            try: self.invite_cache[guild.id] = await guild.invites()
            except: pass

    @tasks.loop(minutes=10)
    async def check_invite_validation(self):
        pending = col_invites.find({"valid": False})
        now = datetime.utcnow()
        for inv in pending:
            if now > (inv["joined_at"] + timedelta(hours=24)):
                col_invites.update_one({"_id": inv["_id"]}, {"$set": {"valid": True}})
                col_users.update_one({"_id": inv["inviter_id"]}, {"$inc": {"coins": 100, "invite_count": 1}})

    @tasks.loop(minutes=1)
    async def check_request_timeouts(self):
        reqs = col_requests.find({})
        now = datetime.utcnow()
        for r in reqs:
            if now > r["expires_at"]:
                col_users.update_one({"_id": r["host_id"]}, {"$inc": {"coins": r["price"]}})
                col_requests.delete_one({"_id": r["_id"]})
                try:
                    ch = self.get_channel(r["msg_channel_id"])
                    if ch:
                        msg = await ch.fetch_message(r["msg_id"])
                        await msg.edit(content=f"❌ **Request Expired.** Coins refunded to <@{r['host_id']}>.", view=None, embed=None)
                except: pass

    @tasks.loop(seconds=30)
    async def check_vouch_timers(self):
        pending = col_vouch.find({})
        now = datetime.utcnow()
        for p in pending:
            start_time = p["start_time"]
            if isinstance(start_time, str): start_time = datetime.fromisoformat(start_time)
            elapsed = (now - start_time).total_seconds() / 60
            channel = self.get_channel(p["channel_id"])
            user = self.get_guild(p.get("guild_id", 0)).get_member(p["user_id"]) if p.get("guild_id") else None

            if not channel:
                col_vouch.delete_one({"_id": p["_id"]})
                continue
            if elapsed >= 10 and not p.get("warned_10"):
                if user: await channel.send(f"⚠️ {user.mention} **Reminder:** `[{p['code_used']}] I got {p['service']}, thanks @admin`")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_10": True}})
            elif elapsed >= 20 and not p.get("warned_20"):
                if user: await channel.send(f"🚨 {user.mention} **FINAL WARNING:** Vouch or Ban.")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_20": True}})
            elif elapsed >= 30:
                warning_channel = self.get_channel(CH_WARNINGS)
                if user and not is_admin(user.id):
                    try: await user.ban(reason="No Vouch (Auto)", delete_message_days=0)
                    except: pass
                    if warning_channel: await warning_channel.send(f"🚫 **Banned:** {user.mention} for no vouch.")
                col_vouch.delete_one({"_id": p["_id"]})
                await channel.delete(reason="Expired")

    @tasks.loop(seconds=60)
    async def check_channel_expiry(self):
        active = col_channels.find({})
        now = datetime.utcnow()
        for c in active:
            if now > c["end_time"]:
                channel = self.get_channel(c["channel_id"])
                if channel: await channel.delete()
                col_users.update_one({"_id": c["owner_id"]}, {"$set": {"current_private_channel_id": None}})
                col_channels.delete_one({"_id": c["_id"]})

bot = EGBot()

def is_admin(user_id): return user_id in ADMIN_IDS

def get_user_data(user_id):
    data = col_users.find_one({"_id": user_id})
    if not data:
        data = {"_id": user_id, "coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None, "invite_count": 0}
        col_users.insert_one(data)
    return data

@bot.event
async def on_invite_create(invite):
    if invite.guild.id in bot.invite_cache:
        bot.invite_cache[invite.guild.id].append(invite)

@bot.event
async def on_invite_delete(invite):
    if invite.guild.id in bot.invite_cache:
        bot.invite_cache[invite.guild.id] = await invite.guild.invites()

@bot.event
async def on_member_join(member):
    c = bot.get_channel(CH_WELCOME)
    if c: await c.send(embed=discord.Embed(description=f"Welcome {member.mention}!\n\n{EG_COND}", color=discord.Color.purple()))
    role = discord.utils.get(member.guild.roles, name="Member")
    if role: await member.add_roles(role)

    invites_before = bot.invite_cache.get(member.guild.id, [])
    invites_after = await member.guild.invites()
    used_invite = None
    for inv in invites_after:
        for old_inv in invites_before:
            if inv.code == old_inv.code and inv.uses > old_inv.uses:
                used_invite = inv
                break
        if used_invite: break
    bot.invite_cache[member.guild.id] = invites_after

    if used_invite:
        col_invites.insert_one({"user_id": member.id, "inviter_id": used_invite.inviter.id, "joined_at": datetime.utcnow(), "valid": False})

@bot.event
async def on_member_remove(member):
    record = col_invites.find_one({"user_id": member.id})
    if record:
        if record["valid"]:
            col_users.update_one({"_id": record["inviter_id"]}, {"$inc": {"coins": -100, "invite_count": -1}})
        col_invites.delete_one({"_id": record["_id"]})

class RequestView(discord.ui.View):
    def __init__(self, request_id, guest_ids):
        super().__init__(timeout=None)
        self.request_id = request_id
        self.guest_ids = guest_ids

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        req = col_requests.find_one({"_id": self.request_id})
        if not req: return await interaction.response.send_message("❌ Request expired.", ephemeral=True)
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

        if req["type"] == "text":
            chan = await guild.create_text_channel(req["name"], category=category, overwrites=overwrites)
        else:
            chan = await guild.create_voice_channel(req["name"], category=category, overwrites=overwrites)

        col_users.update_one({"_id": req["host_id"]}, {"$set": {"current_private_channel_id": chan.id}})
        col_channels.insert_one({"channel_id": chan.id, "owner_id": req["host_id"], "type": req["type"], "end_time": req["end_time"]})

        try: await interaction.message.edit(content=f"✅ **Room Created!** {chan.mention}\nAccepted by: {interaction.user.mention}", view=None, embed=None)
        except: pass
        await chan.send(f"{host.mention} {interaction.user.mention} Welcome to your private room!")

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.guest_ids: return await interaction.response.send_message("❌ Not invited.", ephemeral=True)
        if interaction.user.id in self.guest_ids: self.guest_ids.remove(interaction.user.id)
        await interaction.response.send_message(f"🚫 You declined.", ephemeral=True)

@bot.tree.command(name="makeprivatechannel", description="Request a private channel")
@app_commands.choices(channel_type=[app_commands.Choice(name="Text", value="text"), app_commands.Choice(name="Voice", value="voice")], duration=[app_commands.Choice(name="1 Hour", value=1), app_commands.Choice(name="2 Hours", value=2), app_commands.Choice(name="4 Hours", value=4)])
async def makeprivate(interaction: discord.Interaction, channel_type: str, name: str, duration: int, members: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.response.send_message("🔒 Maintenance Mode.", ephemeral=True)

    uid = interaction.user.id
    data = get_user_data(uid)
    if data.get("current_private_channel_id") and not is_admin(uid): return await interaction.response.send_message("❌ You already have a channel.", ephemeral=True)

    guests = [int(id) for id in re.findall(r'<@!?(\d+)>', members)]
    guests = list(set(guests))
    if uid in guests: guests.remove(uid)
    if len(guests) + 1 < 2 or len(guests) + 1 > 7: return await interaction.response.send_message("❌ Need 2-7 users.", ephemeral=True)

    price = PRICES[channel_type][len(guests)+1][duration]
    if data["coins"] < price: return await interaction.response.send_message(f"❌ Need {price} coins.", ephemeral=True)

    col_users.update_one({"_id": uid}, {"$inc": {"coins": -price}})
    req_id = pymongo.ObjectId()
    
    embed = discord.Embed(title=f"🔒 {channel_type.title()} Room Request", description=f"{interaction.user.mention} wants to open a private room.\n\n**Guests:** {' '.join([f'<@{g}>' for g in guests])}\n**Price Paid:** {price}\n**Duration:** {duration}h\n\n*Waiting for at least 1 guest to Accept...*", color=discord.Color.gold())
    await interaction.response.send_message(embed=embed, view=RequestView(req_id, guests))
    msg = await interaction.original_response()

    col_requests.insert_one({
        "_id": req_id, "host_id": uid, "guests": guests, "type": channel_type, "name": name, "price": price,
        "end_time": datetime.utcnow() + timedelta(hours=duration),
        "expires_at": datetime.utcnow() + timedelta(minutes=30),
        "msg_id": msg.id, "msg_channel_id": interaction.channel.id
    })

@bot.tree.command(name="invites", description="Show valid invites")
async def invites(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    pending = col_invites.count_documents({"inviter_id": interaction.user.id, "valid": False})
    await interaction.response.send_message(f"📩 **Invites:** {d['invite_count']} Valid | {pending} Pending (24h)", ephemeral=True)

@bot.tree.command(name="clear", description="Admin: Clear messages")
async def clear(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction.user.id): return
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Cleared {amount}.", ephemeral=True, delete_after=3)

@bot.tree.command(name="givecoins", description="Admin: Give coins")
async def givecoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return
    get_user_data(user.id)
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"✅ Gave {amount} to {user.mention}", ephemeral=True)

@bot.tree.command(name="daily", description="Claim coins")
async def daily(interaction: discord.Interaction):
    uid = interaction.user.id
    d = get_user_data(uid)
    now = datetime.utcnow()
    if d.get("daily_cd") and not is_admin(uid):
        if now < d["daily_cd"]: return await interaction.response.send_message("⏳ Later.", ephemeral=True)
    col_users.update_one({"_id": uid}, {"$inc": {"coins": 100}, "$set": {"daily_cd": now + timedelta(hours=24)}})
    await interaction.response.send_message("💰 +100 Coins", ephemeral=False)

@bot.tree.command(name="pay", description="Pay coins")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    if amount <= 0 or interaction.user.id == user.id: return await interaction.response.send_message("❌ Invalid.", ephemeral=True)
    s = get_user_data(interaction.user.id)
    if s["coins"] < amount: return await interaction.response.send_message("❌ Low balance.", ephemeral=True)
    get_user_data(user.id)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -amount}})
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"💸 Paid {amount} to {user.mention}", ephemeral=False)

@bot.tree.command(name="status", description="Balance")
async def status(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💳 {d['coins']} Coins", ephemeral=True)

@bot.tree.command(name="addcode", description="Admin: Add code")
async def addcode(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not is_admin(interaction.user.id): return
    col_codes.insert_one({"code": code, "service": service, "email": email, "password": password})
    await interaction.response.send_message(f"✅ Added `{code}`", ephemeral=True)

@bot.tree.command(name="redeem", description="Redeem code")
async def redeem(interaction: discord.Interaction, code: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.response.send_message("🔒 Maintenance.", ephemeral=True)
    uid = interaction.user.id
    d = get_user_data(uid)
    if d.get("last_redeem") and not is_admin(uid):
        if (datetime.utcnow() - d["last_redeem"]) < timedelta(hours=24): return await interaction.response.send_message("⏳ 24h Cooldown.", ephemeral=True)
    cd = col_codes.find_one({"code": code})
    if not cd: return await interaction.response.send_message("❌ Invalid.", ephemeral=True)
    
    guild = interaction.guild
    overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True), guild.me: discord.PermissionOverwrite(read_messages=True)}
    for aid in ADMIN_IDS:
        m = guild.get_member(aid)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    col_codes.delete_one({"code": code})
    chan = await guild.create_text_channel(f"redeem-{interaction.user.name[:10]}", overwrites=overwrites)
    col_users.update_one({"_id": uid}, {"$set": {"last_redeem": datetime.utcnow()}})
    
    # 📝 LOGGING CODE USE
    log_ch = bot.get_channel(CH_CODE_USE_LOG)
    if log_ch: await log_ch.send(f"`{code}` have been use by {interaction.user.mention}")

    col_vouch.insert_one({"channel_id": chan.id, "guild_id": guild.id, "user_id": uid, "code_used": code, "service": cd['service'], "start_time": datetime.utcnow(), "warned_10": False, "warned_20": False})
    embed = discord.Embed(title="🎉 Success", color=discord.Color.green())
    embed.add_field(name="Login", value=f"E: `{cd['email']}`\nP: `{cd['password']}`")
    await chan.send(f"{interaction.user.mention}", embed=embed)
    await chan.send(f"**VOUCH:** `[{code}] I got {cd['service']}, thanks @admin`")
    await interaction.response.send_message(f"✅ {chan.mention}", ephemeral=True)

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

@bot.tree.command(name="lock", description="Admin: Lock")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": True}})
    await interaction.response.send_message("🔒 Locked.")

@bot.tree.command(name="unlock", description="Admin: Unlock")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None)
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": False}})
    await interaction.response.send_message("🔓 Unlocked.")

@bot.tree.command(name="panic", description="Admin: Toggle Panic")
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

@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id == CH_FIND_TEAM:
        await message.delete()
        return
    pending = col_vouch.find_one({"channel_id": message.channel.id, "user_id": message.author.id})
    if pending:
        if re.match(r"^\[.+\] I got .+, thanks <@\d+>$", message.content, re.IGNORECASE):
            await message.add_reaction("✅")
            col_vouch.delete_one({"_id": pending["_id"]})
            if bot.get_channel(CH_VOUCH_LOG): await bot.get_channel(CH_VOUCH_LOG).send(f"✅ {message.author.name} vouched for `{pending['service']}`")
            await asyncio.sleep(5)
            await message.channel.delete()
        else:
            await message.delete()
            await message.channel.send("❌ Format: `[CODE] I got SERVICE, thanks @admin`", delete_after=5)
    await bot.process_commands(message)

bot.run(TOKEN)
