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

# Railway will provide these securely
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

DB_NAME = "enjoined_gaming_db"
ADMIN_IDS = [986251574982606888, 1458812527055212585]

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
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")

    @tasks.loop(seconds=30)
    async def check_vouch_timers(self):
        pending = col_vouch.find({})
        now = datetime.utcnow()
        
        for p in pending:
            start_time = p["start_time"]
            elapsed = (now - start_time).total_seconds() / 60
            channel = self.get_channel(p["channel_id"])
            user = self.get_guild(p.get("guild_id", 0)).get_member(p["user_id"]) if p.get("guild_id") else None

            if not channel:
                col_vouch.delete_one({"_id": p["_id"]})
                continue

            if elapsed >= 10 and not p.get("warned_10"):
                if user: await channel.send(f"⚠️ {user.mention} You have 20 minutes left to vouch! Format: `[CODE] I got [SERVICE], thanks @admin`")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_10": True}})

            elif elapsed >= 20 and not p.get("warned_20"):
                if user: await channel.send(f"🚨 {user.mention} **WARNING:** 10 minutes remaining! Failure to vouch will result in a 3-day ban.")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_20": True}})

            elif elapsed >= 30:
                if user:
                    try:
                        await user.ban(reason="Did not vouch within 30 minutes (Auto-Ban)", delete_message_days=0)
                    except:
                        pass
                col_vouch.delete_one({"_id": p["_id"]})
                await channel.delete(reason="Vouch timer expired")

    @tasks.loop(seconds=60)
    async def check_channel_expiry(self):
        active = col_channels.find({})
        now = datetime.utcnow()
        for c in active:
            if now > c["end_time"]:
                channel = self.get_channel(c["channel_id"])
                if channel:
                    await channel.delete(reason="Rented time expired")
                col_users.update_one({"_id": c["owner_id"]}, {"$set": {"current_private_channel_id": None}})
                col_channels.delete_one({"_id": c["_id"]})

bot = EGBot()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_user_data(user_id):
    data = col_users.find_one({"_id": user_id})
    if not data:
        data = {"_id": user_id, "coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None}
        col_users.insert_one(data)
    return data

# =========================================
# 💰 COMMANDS
# =========================================

@bot.tree.command(name="daily", description="Claim your daily 100 coins")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    data = get_user_data(user_id)
    now = datetime.utcnow()
    last_daily = data.get("daily_cd")

    if last_daily and not is_admin(user_id):
        if now < last_daily:
            return await interaction.response.send_message(f"⏳ Please wait.", ephemeral=True)

    next_reset = now + timedelta(hours=24)
    col_users.update_one({"_id": user_id}, {"$inc": {"coins": 100}, "$set": {"daily_cd": next_reset}})
    await interaction.response.send_message(f"💰 **+100 Coins!**", ephemeral=False)

@bot.tree.command(name="status", description="Check your coins")
async def status(interaction: discord.Interaction):
    data = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💰 Coins: {data['coins']}")

@bot.tree.command(name="addcode", description="Admin: Add a redeem code")
async def addcode(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    col_codes.insert_one({"code": code, "service": service, "email": email, "password": password})
    await interaction.response.send_message(f"✅ Code added.", ephemeral=True)

@bot.tree.command(name="redeem", description="Redeem a code")
async def redeem(interaction: discord.Interaction, code: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.response.send_message("🔒 Panic Mode Enabled.", ephemeral=True)

    user_id = interaction.user.id
    data = get_user_data(user_id)
    now = datetime.utcnow()

    if data.get("last_redeem") and not is_admin(user_id):
        diff = now - data["last_redeem"]
        if diff < timedelta(hours=24): return await interaction.response.send_message("⏳ 24h Cooldown.", ephemeral=True)

    code_data = col_codes.find_one({"code": code})
    if not code_data: return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)

    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    for admin_id in ADMIN_IDS:
        member = guild.get_member(admin_id)
        if member: overwrites[member] = discord.PermissionOverwrite(read_messages=True)

    channel = await guild.create_text_channel(f"redeem-{interaction.user.name[:10]}", overwrites=overwrites)
    
    embed = discord.Embed(title="🎉 Redeem Successful", color=discord.Color.green())
    embed.add_field(name="Service", value=code_data['service'])
    embed.add_field(name="Email", value=f"`{code_data['email']}`")
    embed.add_field(name="Password", value=f"`{code_data['password']}`")
    
    await channel.send(f"{interaction.user.mention}", embed=embed)
    await channel.send(f"**VOUCH FORMAT:**\n`[{code}] I got {code_data['service']}, thanks @admin`")

    col_codes.delete_one({"code": code})
    col_users.update_one({"_id": user_id}, {"$set": {"last_redeem": now}})
    col_vouch.insert_one({"channel_id": channel.id, "guild_id": guild.id, "user_id": user_id, "code_used": code, "service": code_data['service'], "start_time": now, "warned_10": False, "warned_20": False})
    await interaction.response.send_message(f"✅ Redeemed! Check {channel.mention}", ephemeral=True)

@bot.tree.command(name="makeprivatechannel", description="Rent a private channel")
@app_commands.choices(channel_type=[app_commands.Choice(name="Text", value="text"), app_commands.Choice(name="Voice", value="voice")], duration=[app_commands.Choice(name="1 Hour", value=1), app_commands.Choice(name="2 Hours", value=2), app_commands.Choice(name="4 Hours", value=4)])
async def makeprivate(interaction: discord.Interaction, channel_type: str, name: str, duration: int, members: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.response.send_message("🔒 Panic Mode.", ephemeral=True)

    user_id = interaction.user.id
    data = get_user_data(user_id)
    if data.get("current_private_channel_id") and not is_admin(user_id): return await interaction.response.send_message("❌ You already have a channel.", ephemeral=True)

    member_ids = [int(id) for id in re.findall(r'<@!?(\d+)>', members)]
    member_ids = list(set(member_ids))
    if user_id in member_ids: member_ids.remove(user_id)
    total_users = len(member_ids) + 1

    if total_users < 2 or total_users > 7: return await interaction.response.send_message("❌ Users must be between 2 and 7.", ephemeral=True)

    try: price = PRICES[channel_type][total_users][duration]
    except: return await interaction.response.send_message("❌ Config error.", ephemeral=True)

    if data["coins"] < price: return await interaction.response.send_message(f"❌ Need {price} coins.", ephemeral=True)

    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, connect=True, speak=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, connect=True)
    }
    for m_id in member_ids:
        mem = guild.get_member(m_id)
        if mem: overwrites[mem] = discord.PermissionOverwrite(read_messages=True, connect=True, speak=True)

    if channel_type == "text": channel = await guild.create_text_channel(name, overwrites=overwrites)
    else: channel = await guild.create_voice_channel(name, overwrites=overwrites)

    col_users.update_one({"_id": user_id}, {"$inc": {"coins": -price}, "$set": {"current_private_channel_id": channel.id}})
    col_channels.insert_one({"channel_id": channel.id, "owner_id": user_id, "type": channel_type, "end_time": datetime.utcnow() + timedelta(hours=duration)})
    
    if channel_type == "text": await channel.send(f"✅ Private Channel Active for {duration}h. Owner: {interaction.user.mention}")
    await interaction.response.send_message(f"✅ Channel created: {channel.mention}", ephemeral=True)

@bot.tree.command(name="findteam", description="Find a team")
async def findteam(interaction: discord.Interaction, role: str, level: str, message: str):
    if "find-team" not in interaction.channel.name: return await interaction.response.send_message("❌ Wrong channel.", ephemeral=True)
    embed = discord.Embed(title="🎮 Free Fire Team Request", color=discord.Color.orange())
    embed.add_field(name="Player", value=interaction.user.mention)
    embed.add_field(name="Role", value=role)
    embed.add_field(name="Level", value=level)
    embed.add_field(name="Message", value=message)
    await interaction.response.send_message(embed=embed, delete_after=1800)

@bot.tree.command(name="lock", description="Admin: Lock")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": True}})
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Locked.")

@bot.tree.command(name="unlock", description="Admin: Unlock")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": False}})
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Unlocked.")

@bot.tree.command(name="panic", description="Admin: Toggle Panic")
async def panic(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    curr = col_settings.find_one({"_id": "config"})
    col_settings.update_one({"_id": "config"}, {"$set": {"panic": not curr["panic"]}})
    await interaction.response.send_message(f"🚨 Panic: {not curr['panic']}", ephemeral=True)

@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name="Member")
    if role: await member.add_roles(role)
    channel = discord.utils.get(member.guild.text_channels, name="welcome")
    if channel: await channel.send(f"Welcome {member.mention}!\n{EG_COND}")

@bot.event
async def on_message(message):
    if message.author.bot: return
    pending = col_vouch.find_one({"channel_id": message.channel.id, "user_id": message.author.id})
    if pending:
        if re.match(r"^\[.+\] I got .+, thanks <@\d+>$", message.content, re.IGNORECASE):
            await message.add_reaction("✅")
            await message.channel.send("✅ Vouch accepted!")
            col_vouch.delete_one({"_id": pending["_id"]})
            await asyncio.sleep(10)
            await message.channel.delete()
        else:
            await message.delete()
            await message.channel.send(f"❌ WRONG FORMAT!\nUse: `[{pending['code_used']}] I got {pending['service']}, thanks @admin`", delete_after=5)
    await bot.process_commands(message)

bot.run(TOKEN)
