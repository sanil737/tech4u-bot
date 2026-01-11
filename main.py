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

# Secrets from Railway
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

DB_NAME = "enjoined_gaming_db"
# ADMIN IDS (Bypass all limits)
ADMIN_IDS = [986251574982606888, 1458812527055212585]

# 📌 CHANNEL & CATEGORY IDS
CH_WELCOME = 1459444229255200971
CH_FIND_TEAM = 1459469475849175304
CH_VOUCH_LOG = 1459448284530610288
CH_WARNINGS = 1459448651704303667
CAT_PRIVATE_ROOMS = 1459557142850830489

# Pricing Tables
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
        super().__init__(command_prefix=".", intents=intents)

    async def setup_hook(self):
        self.check_vouch_timers.start()
        self.check_channel_expiry.start()
        await self.tree.sync() 
        print("✅ Commands Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")

    # ⏳ Vouch Timer Task (Auto Ban & Log)
    @tasks.loop(seconds=30)
    async def check_vouch_timers(self):
        pending = col_vouch.find({})
        now = datetime.utcnow()
        
        for p in pending:
            start_time = p["start_time"]
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)

            elapsed = (now - start_time).total_seconds() / 60
            channel = self.get_channel(p["channel_id"])
            user = self.get_guild(p.get("guild_id", 0)).get_member(p["user_id"]) if p.get("guild_id") else None

            if not channel:
                col_vouch.delete_one({"_id": p["_id"]})
                continue

            if elapsed >= 10 and not p.get("warned_10"):
                if user: await channel.send(f"⚠️ {user.mention} **Reminder:** Please vouch within 20 minutes.\nFormat: `[{p['code_used']}] I got {p['service']}, thanks @admin`")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_10": True}})

            elif elapsed >= 20 and not p.get("warned_20"):
                if user: await channel.send(f"🚨 {user.mention} **FINAL WARNING:** 10 minutes remaining!\nIf you do not vouch, you will be **BANNED**.")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_20": True}})

            elif elapsed >= 30:
                warning_channel = self.get_channel(CH_WARNINGS)
                if user and not is_admin(user.id):
                    try:
                        await user.ban(reason="Failed to vouch (Auto-Ban)", delete_message_days=0)
                    except: pass
                    
                    if warning_channel:
                        embed = discord.Embed(title="🚫 User Punishment Log", color=discord.Color.red())
                        embed.add_field(name="User", value=f"{user.mention}", inline=True)
                        embed.add_field(name="Action", value="**Banned**", inline=True)
                        embed.add_field(name="Reason", value=f"No vouch for **{p['service']}**.", inline=False)
                        await warning_channel.send(embed=embed)
                
                col_vouch.delete_one({"_id": p["_id"]})
                await channel.delete(reason="Expired")

    # ⏳ Channel Expiry Task
    @tasks.loop(seconds=60)
    async def check_channel_expiry(self):
        active = col_channels.find({})
        now = datetime.utcnow()
        for c in active:
            if now > c["end_time"]:
                channel = self.get_channel(c["channel_id"])
                if channel:
                    await channel.delete(reason="Time expired")
                col_users.update_one({"_id": c["owner_id"]}, {"$set": {"current_private_channel_id": None}})
                col_channels.delete_one({"_id": c["_id"]})

bot = EGBot()

# =========================================
# 🛠️ HELPERS
# =========================================

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_user_data(user_id):
    data = col_users.find_one({"_id": user_id})
    if not data:
        data = {"_id": user_id, "coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None}
        col_users.insert_one(data)
    return data

# =========================================
# 🔐 PRIVATE CHANNELS (INVITE SYSTEM)
# =========================================

class JoinPrivateView(discord.ui.View):
    def __init__(self, authorized_ids):
        super().__init__(timeout=None)
        self.authorized_ids = authorized_ids

    @discord.ui.button(label="✅ Join Channel", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.authorized_ids:
            return await interaction.response.send_message("❌ You were not invited to this channel.", ephemeral=True)
        
        # Grant Permission
        await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True, connect=True, speak=True)
        await interaction.response.send_message(f"✅ Welcome {interaction.user.mention}!", ephemeral=True)

@bot.tree.command(name="makeprivatechannel", description="Rent private channel")
@app_commands.choices(channel_type=[app_commands.Choice(name="Text", value="text"), app_commands.Choice(name="Voice", value="voice")], duration=[app_commands.Choice(name="1 Hour", value=1), app_commands.Choice(name="2 Hours", value=2), app_commands.Choice(name="4 Hours", value=4)])
async def makeprivate(interaction: discord.Interaction, channel_type: str, name: str, duration: int, members: str):
    config = col_settings.find_one({"_id": "config"})
    # Correct Panic Logic: If panic ON and User NOT Admin -> Block
    if config["panic"] and not is_admin(interaction.user.id): 
        return await interaction.response.send_message("🔒 **Maintenance Mode:** Creating channels is currently disabled.", ephemeral=True)

    user_id = interaction.user.id
    data = get_user_data(user_id)
    if data.get("current_private_channel_id") and not is_admin(user_id): 
        return await interaction.response.send_message("❌ You already have an active channel.", ephemeral=True)

    # Parse invites
    guest_ids = [int(id) for id in re.findall(r'<@!?(\d+)>', members)]
    guest_ids = list(set(guest_ids)) # Remove duplicates
    if user_id in guest_ids: guest_ids.remove(user_id) # Remove self
    
    total_users_count = len(guest_ids) + 1 # Owner + Guests

    if total_users_count < 2 or total_users_count > 7: 
        return await interaction.response.send_message("❌ Total users must be between 2 and 7.", ephemeral=True)

    try:
        price = PRICES[channel_type][total_users_count][duration]
    except:
        return await interaction.response.send_message(f"❌ Price config not found for {total_users_count} users.", ephemeral=True)

    if data["coins"] < price: 
        return await interaction.response.send_message(f"❌ Insufficient Funds. Cost: {price}, You have: {data['coins']}", ephemeral=True)

    # Create Channel in Category
    guild = interaction.guild
    category = guild.get_channel(CAT_PRIVATE_ROOMS)
    
    # Initial Perms: Only Owner and Bot
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, connect=True, manage_channels=True)
    }

    if channel_type == "text": 
        channel = await guild.create_text_channel(name, overwrites=overwrites, category=category)
    else: 
        channel = await guild.create_voice_channel(name, overwrites=overwrites, category=category)

    # Deduct Coins & Save
    col_users.update_one({"_id": user_id}, {"$inc": {"coins": -price}, "$set": {"current_private_channel_id": channel.id}})
    col_channels.insert_one({"channel_id": channel.id, "owner_id": user_id, "type": channel_type, "end_time": datetime.utcnow() + timedelta(hours=duration)})
    
    # Send Invitation in the new channel
    guest_mentions = " ".join([f"<@{uid}>" for uid in guest_ids])
    
    embed = discord.Embed(title="📨 Private Channel Invitation", description=f"{interaction.user.mention} has invited you to join this private room.\n**Click the button below to join.**", color=discord.Color.green())
    if guest_mentions:
        await channel.send(f"{guest_mentions}", embed=embed, view=JoinPrivateView(guest_ids))
    else:
        await channel.send("Channel created.", embed=embed)

    await interaction.response.send_message(f"✅ Channel Created: {channel.mention}\nGuests have been invited.", ephemeral=True)


# =========================================
# 📢 COMMANDS (Ann, Daily, Pay, etc)
# =========================================

@bot.tree.command(name="ann", description="Admin: Make an announcement")
async def ann(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    embed = discord.Embed(title=title, description=message, color=discord.Color.blue())
    embed.set_footer(text=f"Sent by {interaction.user.display_name}")
    try:
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Sent to {channel.mention}", ephemeral=True)
    except: await interaction.response.send_message("❌ Failed to send.", ephemeral=True)

@bot.tree.command(name="daily", description="Claim 100 coins")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    data = get_user_data(user_id)
    now = datetime.utcnow()
    last = data.get("daily_cd")
    if last and not is_admin(user_id):
        if now < last:
            diff = last - now
            return await interaction.response.send_message(f"⏳ Come back in **{int(diff.total_seconds()//3600)} hours**.", ephemeral=True)
    col_users.update_one({"_id": user_id}, {"$inc": {"coins": 100}, "$set": {"daily_cd": now + timedelta(hours=24)}})
    await interaction.response.send_message(f"💰 **+100 Coins!**", ephemeral=False)

@bot.tree.command(name="pay", description="Transfer coins")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    if amount <= 0 or interaction.user.id == user.id: return await interaction.response.send_message("❌ Invalid amount or user.", ephemeral=True)
    sender = get_user_data(interaction.user.id)
    if sender["coins"] < amount: return await interaction.response.send_message("❌ Not enough coins.", ephemeral=True)
    get_user_data(user.id)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -amount}})
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"💸 {interaction.user.mention} paid **{amount}** to {user.mention}.", ephemeral=False)

@bot.tree.command(name="addcoins", description="Admin: Add coins")
async def addcoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return
    get_user_data(user.id)
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"✅ Added {amount} to {user.mention}.", ephemeral=True)

@bot.tree.command(name="status", description="Check wallet")
async def status(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💳 Balance: {d['coins']}", ephemeral=True)

# =========================================
# 🎁 REDEEM SYSTEM
# =========================================

@bot.tree.command(name="addcode", description="Admin: Add code")
async def addcode(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not is_admin(interaction.user.id): return
    col_codes.insert_one({"code": code, "service": service, "email": email, "password": password})
    await interaction.response.send_message(f"✅ Code `{code}` added.", ephemeral=True)

@bot.tree.command(name="redeem", description="Redeem a code")
async def redeem(interaction: discord.Interaction, code: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.response.send_message("🔒 Maintenance Mode.", ephemeral=True)

    uid = interaction.user.id
    d = get_user_data(uid)
    now = datetime.utcnow()
    
    if d.get("last_redeem") and not is_admin(uid):
        if (now - d["last_redeem"]) < timedelta(hours=24): return await interaction.response.send_message("⏳ 24h Cooldown.", ephemeral=True)

    cd = col_codes.find_one({"code": code})
    if not cd: return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)

    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    for aid in ADMIN_IDS:
        m = guild.get_member(aid)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    chan = await guild.create_text_channel(f"redeem-{interaction.user.name[:10]}", overwrites=overwrites)
    embed = discord.Embed(title="🎉 Redeem Success", color=discord.Color.green())
    embed.add_field(name="Service", value=cd['service'])
    embed.add_field(name="Login", value=f"E: `{cd['email']}`\nP: `{cd['password']}`")
    await chan.send(f"{interaction.user.mention}", embed=embed)
    await chan.send(f"**VOUCH REQUIRED:**\n`[{code}] I got {cd['service']}, thanks @admin`")

    col_codes.delete_one({"code": code})
    col_users.update_one({"_id": uid}, {"$set": {"last_redeem": now}})
    col_vouch.insert_one({"channel_id": chan.id, "guild_id": guild.id, "user_id": uid, "code_used": code, "service": cd['service'], "start_time": now, "warned_10": False, "warned_20": False})
    await interaction.response.send_message(f"✅ Check {chan.mention}", ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Admin: Ticket")
async def ticketpanel(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    
    class TView(discord.ui.View):
        def __init__(self): super().__init__(timeout=None)
        @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green, custom_id="opticket")
        async def op(self, intr: discord.Interaction, b: discord.ui.Button):
            ow = {
                intr.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                intr.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                intr.guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            for aid in ADMIN_IDS:
                m = intr.guild.get_member(aid)
                if m: ow[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            c = await intr.guild.create_text_channel(f"ticket-{intr.user.name}", overwrites=ow)
            await c.send(f"{intr.user.mention} Support here.", view=None)
            await intr.response.send_message(f"✅ {c.mention}", ephemeral=True)

    await interaction.channel.send("📩 **Support**", view=TView())
    await interaction.response.send_message("Done", ephemeral=True)

@bot.tree.command(name="close", description="Close ticket/redeem")
async def close(interaction: discord.Interaction):
    if "ticket-" in interaction.channel.name or "redeem-" in interaction.channel.name:
        await interaction.response.send_message("👋 Closing...")
        await asyncio.sleep(3)
        await interaction.channel.delete()
    else: await interaction.response.send_message("❌ Not a ticket.", ephemeral=True)

# =========================================
# 🛡️ MODERATION (LOCK & PANIC)
# =========================================

@bot.tree.command(name="lock", description="Admin: Lock Channel")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    
    # 1. Lock @everyone
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    
    # 2. Lock "Member" role if exists (Often overrides everyone)
    role = discord.utils.get(interaction.guild.roles, name="Member")
    if role:
        await interaction.channel.set_permissions(role, send_messages=False)
        
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": True}})
    await interaction.response.send_message("🔒 **Channel Locked** (Everyone & Member role muted).")

@bot.tree.command(name="unlock", description="Admin: Unlock Channel")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    
    # Reset to default (usually None means inherit permissions)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None)
    role = discord.utils.get(interaction.guild.roles, name="Member")
    if role:
        await interaction.channel.set_permissions(role, send_messages=None)
        
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": False}})
    await interaction.response.send_message("🔓 **Channel Unlocked**.")

@bot.tree.command(name="panic", description="Admin: Toggle Panic")
async def panic(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    curr = col_settings.find_one({"_id": "config"})
    new_state = not curr["panic"]
    col_settings.update_one({"_id": "config"}, {"$set": {"panic": new_state}})
    await interaction.response.send_message(f"🚨 Panic Mode: **{'ON' if new_state else 'OFF'}**", ephemeral=True)

# =========================================
# 🎮 EVENTS (Join, Message, FindTeam)
# =========================================

@bot.tree.command(name="findteam", description="Find Team")
async def findteam(interaction: discord.Interaction, role: str, level: str, message: str):
    if interaction.channel.id != CH_FIND_TEAM:
        return await interaction.response.send_message(f"❌ Use <#{CH_FIND_TEAM}> only.", ephemeral=True)
    embed = discord.Embed(title="🎮 Team Request", color=discord.Color.orange())
    embed.add_field(name="User", value=interaction.user.mention)
    embed.add_field(name="Details", value=f"**Role:** {role}\n**Level:** {level}\n**Note:** {message}")
    await interaction.response.send_message(embed=embed, delete_after=1800)

@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name="Member")
    if role: await member.add_roles(role)
    c = bot.get_channel(CH_WELCOME)
    if c: 
        embed = discord.Embed(description=f"Welcome {member.mention}!", color=discord.Color.purple())
        embed.add_field(name="Rules", value=EG_COND)
        await c.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot: return

    # 🚫 Restrict #find-team chat (Only bot embeds allowed)
    if message.channel.id == CH_FIND_TEAM:
        # Delete ANY message that isn't from the bot
        await message.delete()
        return

    # Vouch Logic
    pending = col_vouch.find_one({"channel_id": message.channel.id, "user_id": message.author.id})
    if pending:
        if re.match(r"^\[.+\] I got .+, thanks <@\d+>$", message.content, re.IGNORECASE):
            await message.add_reaction("✅")
            await message.channel.send("✅ Vouch Confirmed!")
            col_vouch.delete_one({"_id": pending["_id"]})
            log = bot.get_channel(CH_VOUCH_LOG)
            if log: await log.send(f"✅ **Log:** {message.author.name} vouched for `{pending['service']}`.")
            await asyncio.sleep(5)
            await message.channel.delete()
        else:
            await message.delete()
            await message.channel.send(f"❌ **FORMAT:** `[{pending['code_used']}] I got {pending['service']}, thanks @admin`", delete_after=5)

    await bot.process_commands(message)

bot.run(TOKEN)
