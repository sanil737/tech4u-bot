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
ADMIN_IDS = [986251574982606888, 1458812527055212585]

# 📌 CHANNEL IDS (Configured)
CH_WELCOME = 1459444229255200971
CH_FIND_TEAM = 1459469475849175304
CH_VOUCH_LOG = 1459448284530610288
CH_WARNINGS = 1459448651704303667

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

            # 10m Reminder
            if elapsed >= 10 and not p.get("warned_10"):
                if user: await channel.send(f"⚠️ {user.mention} **Reminder:** Please vouch within 20 minutes.\nFormat: `[{p['code_used']}] I got {p['service']}, thanks @admin`")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_10": True}})

            # 20m Warning
            elif elapsed >= 20 and not p.get("warned_20"):
                if user: await channel.send(f"🚨 {user.mention} **FINAL WARNING:** 10 minutes remaining!\nIf you do not vouch, you will be **BANNED**.")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_20": True}})

            # 30m BAN ACTION
            elif elapsed >= 30:
                warning_channel = self.get_channel(CH_WARNINGS)
                
                if user and not is_admin(user.id):
                    # 1. Ban User
                    try:
                        await user.ban(reason="Failed to vouch after redeem (Auto-Ban)", delete_message_days=0)
                        ban_status = "✅ User Banned"
                    except Exception as e:
                        ban_status = f"❌ Ban Failed ({e})"

                    # 2. Log to Warnings Channel (Good English)
                    if warning_channel:
                        embed = discord.Embed(title="🚫 User Punishment Log", color=discord.Color.red())
                        embed.add_field(name="👤 User", value=f"{user.mention} (`{user.id}`)", inline=True)
                        embed.add_field(name="📉 Action", value="**Banned from Server**", inline=True)
                        embed.add_field(name="📝 Reason", value=f"User failed to provide a vouch for **{p['service']}** within 30 minutes.", inline=False)
                        embed.set_footer(text=f"Code used: {p['code_used']}")
                        await warning_channel.send(embed=embed)
                
                # Cleanup
                col_vouch.delete_one({"_id": p["_id"]})
                await channel.delete(reason="Vouch timer expired")

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
# 📢 ANNOUNCEMENT SYSTEM
# =========================================

@bot.tree.command(name="ann", description="Admin: Make an announcement")
async def ann(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

    embed = discord.Embed(title=title, description=message, color=discord.Color.blue())
    embed.set_footer(text=f"Sent by {interaction.user.display_name}")
    
    try:
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Announcement sent to {channel.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to send: {e}", ephemeral=True)

# =========================================
# 💰 ECONOMY
# =========================================

@bot.tree.command(name="daily", description="Claim 100 coins")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    data = get_user_data(user_id)
    now = datetime.utcnow()
    last_daily = data.get("daily_cd")

    if last_daily and not is_admin(user_id):
        if now < last_daily:
            diff = last_daily - now
            hours = int(diff.total_seconds() // 3600)
            return await interaction.response.send_message(f"⏳ Come back in **{hours} hours**.", ephemeral=True)

    next_reset = now + timedelta(hours=24)
    col_users.update_one({"_id": user_id}, {"$inc": {"coins": 100}, "$set": {"daily_cd": next_reset}})
    await interaction.response.send_message(f"💰 **+100 Coins!**", ephemeral=False)

@bot.tree.command(name="pay", description="Transfer coins")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    sender_id = interaction.user.id
    receiver_id = user.id

    if amount <= 0: return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    if sender_id == receiver_id: return await interaction.response.send_message("❌ Can't pay yourself.", ephemeral=True)

    sender_data = get_user_data(sender_id)
    if sender_data["coins"] < amount:
        return await interaction.response.send_message(f"❌ Not enough coins! You have {sender_data['coins']}.", ephemeral=True)

    get_user_data(receiver_id)
    col_users.update_one({"_id": sender_id}, {"$inc": {"coins": -amount}})
    col_users.update_one({"_id": receiver_id}, {"$inc": {"coins": amount}})

    await interaction.response.send_message(f"💸 {interaction.user.mention} paid **{amount} coins** to {user.mention}.", ephemeral=False)

@bot.tree.command(name="addcoins", description="Admin: Add coins")
async def addcoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    get_user_data(user.id)
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"✅ Added {amount} coins to {user.mention}.", ephemeral=True)

@bot.tree.command(name="status", description="Check wallet")
async def status(interaction: discord.Interaction):
    data = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💳 **Balance:** {data['coins']} coins", ephemeral=True)

# =========================================
# 🎁 REDEEM & TICKETS
# =========================================

@bot.tree.command(name="addcode", description="Admin: Add code")
async def addcode(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    col_codes.insert_one({"code": code, "service": service, "email": email, "password": password})
    await interaction.response.send_message(f"✅ Code `{code}` added.", ephemeral=True)

@bot.tree.command(name="redeem", description="Redeem a code")
async def redeem(interaction: discord.Interaction, code: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.response.send_message("🔒 System Locked.", ephemeral=True)

    user_id = interaction.user.id
    data = get_user_data(user_id)
    now = datetime.utcnow()

    if data.get("last_redeem") and not is_admin(user_id):
        diff = now - data["last_redeem"]
        if diff < timedelta(hours=24): return await interaction.response.send_message("⏳ One redeem per 24h.", ephemeral=True)

    code_data = col_codes.find_one({"code": code})
    if not code_data: return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)

    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    # Admins see channel
    for aid in ADMIN_IDS:
        m = guild.get_member(aid)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    channel = await guild.create_text_channel(f"redeem-{interaction.user.name[:10]}", overwrites=overwrites)
    
    embed = discord.Embed(title="🎉 Redeem Successful", color=discord.Color.green())
    embed.add_field(name="Service", value=code_data['service'])
    embed.add_field(name="Login Info", value=f"Email: `{code_data['email']}`\nPass: `{code_data['password']}`")
    
    await channel.send(f"{interaction.user.mention}", embed=embed)
    await channel.send(f"**VOUCH REQUIRED:**\n`[{code}] I got {code_data['service']}, thanks @admin`\n*You have 30 minutes or you will be banned.*")

    col_codes.delete_one({"code": code})
    col_users.update_one({"_id": user_id}, {"$set": {"last_redeem": now}})
    col_vouch.insert_one({"channel_id": channel.id, "guild_id": guild.id, "user_id": user_id, "code_used": code, "service": code_data['service'], "start_time": now, "warned_10": False, "warned_20": False})
    
    await interaction.response.send_message(f"✅ Redeemed in {channel.mention}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green, custom_id="open_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        for aid in ADMIN_IDS:
            m = interaction.guild.get_member(aid)
            if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        chan = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name}", overwrites=overwrites)
        await chan.send(f"{interaction.user.mention} Support will be with you.", view=None)
        await interaction.response.send_message(f"✅ {chan.mention}", ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Admin: Send ticket button")
async def ticketpanel(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.send("📩 **Need Help?**", view=TicketView())
    await interaction.response.send_message("Sent.", ephemeral=True)

@bot.tree.command(name="close", description="Close ticket")
async def close(interaction: discord.Interaction):
    if "ticket-" in interaction.channel.name or "redeem-" in interaction.channel.name:
        await interaction.response.send_message("👋 Closing in 5s...")
        await asyncio.sleep(5)
        await interaction.channel.delete()
    else:
        await interaction.response.send_message("❌ Not a ticket.", ephemeral=True)

# =========================================
# 🔐 PRIVATE CHANNELS
# =========================================

@bot.tree.command(name="makeprivatechannel", description="Rent private channel")
@app_commands.choices(channel_type=[app_commands.Choice(name="Text", value="text"), app_commands.Choice(name="Voice", value="voice")], duration=[app_commands.Choice(name="1 Hour", value=1), app_commands.Choice(name="2 Hours", value=2), app_commands.Choice(name="4 Hours", value=4)])
async def makeprivate(interaction: discord.Interaction, channel_type: str, name: str, duration: int, members: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id): return await interaction.response.send_message("🔒 Panic Mode.", ephemeral=True)

    user_id = interaction.user.id
    data = get_user_data(user_id)
    if data.get("current_private_channel_id") and not is_admin(user_id): return await interaction.response.send_message("❌ Already have a channel.", ephemeral=True)

    member_ids = [int(id) for id in re.findall(r'<@!?(\d+)>', members)]
    member_ids = list(set(member_ids))
    if user_id in member_ids: member_ids.remove(user_id)
    total_users = len(member_ids) + 1

    if total_users < 2 or total_users > 7: return await interaction.response.send_message("❌ 2-7 users required.", ephemeral=True)

    price = PRICES[channel_type][total_users][duration]
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
    
    await interaction.response.send_message(f"✅ Created {channel.mention} for {price} coins.", ephemeral=True)

# =========================================
# 🎮 EXTRA & EVENTS
# =========================================

@bot.tree.command(name="findteam", description="Find Team")
async def findteam(interaction: discord.Interaction, role: str, level: str, message: str):
    if interaction.channel.id != CH_FIND_TEAM:
        return await interaction.response.send_message(f"❌ Use <#{CH_FIND_TEAM}> only.", ephemeral=True)
    
    embed = discord.Embed(title="🎮 Team Request", color=discord.Color.orange())
    embed.add_field(name="User", value=interaction.user.mention)
    embed.add_field(name="Info", value=f"**Role:** {role}\n**Level:** {level}\n**Note:** {message}")
    await interaction.response.send_message(embed=embed, delete_after=1800)

@bot.event
async def on_member_join(member):
    # Auto Role
    role = discord.utils.get(member.guild.roles, name="Member")
    if role: await member.add_roles(role)
    
    # Welcome
    channel = bot.get_channel(CH_WELCOME)
    if channel: 
        embed = discord.Embed(title="👋 Welcome to enjoined_gaming!", description=f"Hello {member.mention}!", color=discord.Color.purple())
        embed.add_field(name="📜 Rules", value=EG_COND)
        await channel.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot: return

    # Vouch Logic
    pending = col_vouch.find_one({"channel_id": message.channel.id, "user_id": message.author.id})
    if pending:
        # Check strict format
        if re.match(r"^\[.+\] I got .+, thanks <@\d+>$", message.content, re.IGNORECASE):
            await message.add_reaction("✅")
            await message.channel.send("✅ Vouch Confirmed! Closing...")
            col_vouch.delete_one({"_id": pending["_id"]})
            
            # Log to Vouch Log Channel
            log_chan = bot.get_channel(CH_VOUCH_LOG)
            if log_chan:
                await log_chan.send(f"✅ **Vouch Log:** {message.author.mention} vouched for `{pending['service']}`.")

            await asyncio.sleep(5)
            await message.channel.delete()
        else:
            await message.delete()
            await message.channel.send(f"❌ **WRONG FORMAT!**\nCopy this:\n`[{pending['code_used']}] I got {pending['service']}, thanks @admin`", delete_after=10)
    
    await bot.process_commands(message)

bot.run(TOKEN)
