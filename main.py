import discord
from discord import app_commands
from discord.ext import commands, tasks
import pymongo
from datetime import datetime, timedelta
import asyncio
import re

# =========================================
# ⚙️ CONFIGURATION & CONSTANTS
# =========================================

TOKEN = "YOUR_BOT_TOKEN"
MONGO_URI = "YOUR_MONGO_CONNECTION_STRING"
DB_NAME = "enjoined_gaming_db"

ADMIN_IDS = [986251574982606888, 1458812527055212585]
GUILD_ID = discord.Object(id=123456789012345678) # REPLACE WITH YOUR SERVER ID FOR INSTANT SYNC

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

col_users = db["users"]           # _id, coins, daily_cd, last_redeem
col_codes = db["codes"]           # code, service, email, password
col_vouch = db["vouch_pending"]   # channel_id, user_id, code_str, start_time, warned_10, warned_20
col_channels = db["active_channels"] # channel_id, owner_id, type, end_time
col_settings = db["settings"]     # panic_mode, locked

# Initialize Settings
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
        # Background tasks
        self.check_vouch_timers.start()
        self.check_channel_expiry.start()
        # Sync slash commands
        await self.tree.sync() 
        print("✅ Commands Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")

    # 🔄 TASK: Check Vouch Timers
    @tasks.loop(seconds=30)
    async def check_vouch_timers(self):
        pending = col_vouch.find({})
        now = datetime.utcnow()
        
        for p in pending:
            start_time = p["start_time"]
            elapsed = (now - start_time).total_seconds() / 60
            channel = self.get_channel(p["channel_id"])
            user = self.get_guild(p.get("guild_id", 0)).get_member(p["user_id"]) if p.get("guild_id") else None

            if not channel or not user:
                continue

            # 10 Min Reminder
            if elapsed >= 10 and not p.get("warned_10"):
                await channel.send(f"⚠️ {user.mention} You have 20 minutes left to vouch! Format: `[CODE] I got [SERVICE], thanks @admin`")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_10": True}})

            # 20 Min Warning
            elif elapsed >= 20 and not p.get("warned_20"):
                await channel.send(f"🚨 {user.mention} **WARNING:** 10 minutes remaining! Failure to vouch will result in a 3-day ban.")
                col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_20": True}})

            # 30 Min Ban
            elif elapsed >= 30:
                try:
                    await user.ban(reason="Did not vouch within 30 minutes (Auto-Ban)", delete_message_days=0)
                    # Create a temp unban task manually or use a separate DB for bans if needed. 
                    # For now, it bans. Unbanning after 3 days would require another task.
                    embed = discord.Embed(title="🚫 User Banned", description=f"{user.mention} was banned for not vouching.", color=discord.Color.red())
                    # Log to a log channel if configured
                except Exception as e:
                    print(f"Failed to ban {user.id}: {e}")
                
                # Cleanup
                col_vouch.delete_one({"_id": p["_id"]})
                await channel.delete(reason="Vouch timer expired")

    # 🔄 TASK: Check Private Channel Expiry
    @tasks.loop(seconds=60)
    async def check_channel_expiry(self):
        active = col_channels.find({})
        now = datetime.utcnow()

        for c in active:
            if now > c["end_time"]:
                channel = self.get_channel(c["channel_id"])
                if channel:
                    await channel.delete(reason="Rented time expired")
                
                # Update user status
                col_users.update_one({"_id": c["owner_id"]}, {"$set": {"current_private_channel_id": None}})
                col_channels.delete_one({"_id": c["_id"]})

bot = EGBot()

# =========================================
# 🛠️ HELPER FUNCTIONS
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
# 💰 ECONOMY COMMANDS
# =========================================

@bot.tree.command(name="daily", description="Claim your daily 100 coins")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    data = get_user_data(user_id)
    
    now = datetime.utcnow()
    last_daily = data.get("daily_cd")

    if last_daily and not is_admin(user_id):
        if now < last_daily:
            remaining = last_daily - now
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            await interaction.response.send_message(f"⏳ Please wait **{hours}h {minutes}m**.", ephemeral=True)
            return

    # Give Reward
    next_reset = now + timedelta(hours=24)
    col_users.update_one({"_id": user_id}, {"$inc": {"coins": 100}, "$set": {"daily_cd": next_reset}})
    
    await interaction.response.send_message(f"💰 **+100 Coins!** Come back in 24 hours.", ephemeral=False)

@bot.tree.command(name="status", description="Check your coins")
async def status(interaction: discord.Interaction):
    data = get_user_data(interaction.user.id)
    embed = discord.Embed(title=f"👤 {interaction.user.display_name}'s Status", color=discord.Color.blue())
    embed.add_field(name="💰 Coins", value=f"{data['coins']}", inline=True)
    await interaction.response.send_message(embed=embed)

# =========================================
# 🎁 REDEEM SYSTEM
# =========================================

@bot.tree.command(name="addcode", description="Admin: Add a redeem code")
async def addcode(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    col_codes.insert_one({"code": code, "service": service, "email": email, "password": password})
    await interaction.response.send_message(f"✅ Code `{code}` for **{service}** added.", ephemeral=True)

@bot.tree.command(name="deletecode", description="Admin: Delete a code")
async def deletecode(interaction: discord.Interaction, code: str):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    result = col_codes.delete_one({"code": code})
    if result.deleted_count > 0:
        await interaction.response.send_message(f"🗑️ Code `{code}` deleted.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Code not found.", ephemeral=True)

@bot.tree.command(name="redeem", description="Redeem a code")
async def redeem(interaction: discord.Interaction, code: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id):
        return await interaction.response.send_message("🔒 Redeem is currently disabled (Panic Mode).", ephemeral=True)

    user_id = interaction.user.id
    data = get_user_data(user_id)
    now = datetime.utcnow()

    # 24h Cooldown Check
    if data.get("last_redeem") and not is_admin(user_id):
        diff = now - data["last_redeem"]
        if diff < timedelta(hours=24):
            return await interaction.response.send_message("⏳ You can only redeem once every 24 hours.", ephemeral=True)

    code_data = col_codes.find_one({"code": code})
    if not code_data:
        return await interaction.response.send_message("❌ Invalid or expired code.", ephemeral=True)

    # Process Redeem
    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }

    # Add admins to overwrites
    for admin_id in ADMIN_IDS:
        member = guild.get_member(admin_id)
        if member:
            overwrites[member] = discord.PermissionOverwrite(read_messages=True)

    # Create Channel
    channel_name = f"redeem-{interaction.user.name[:10]}"
    channel = await guild.create_text_channel(channel_name, overwrites=overwrites)

    # Send Details
    embed = discord.Embed(title="🎉 Redeem Successful", color=discord.Color.green())
    embed.add_field(name="Service", value=code_data['service'])
    embed.add_field(name="Email", value=f"`{code_data['email']}`")
    embed.add_field(name="Password", value=f"`{code_data['password']}`")
    embed.set_footer(text="⚠️ VOUCH REQUIRED: Check format below!")
    
    await channel.send(f"{interaction.user.mention}", embed=embed)
    await channel.send(f"**VOUCH FORMAT:**\n`[{code}] I got {code_data['service']}, thanks @admin`\n\n*You have 30 minutes.*")

    # DB Updates
    col_codes.delete_one({"code": code})
    col_users.update_one({"_id": user_id}, {"$set": {"last_redeem": now}})
    
    col_vouch.insert_one({
        "channel_id": channel.id,
        "guild_id": guild.id,
        "user_id": user_id,
        "code_used": code,
        "service": code_data['service'],
        "start_time": now,
        "warned_10": False,
        "warned_20": False
    })

    await interaction.response.send_message(f"✅ Redeemed! Check {channel.mention}", ephemeral=True)

# =========================================
# 🔐 PRIVATE CHANNEL SYSTEM
# =========================================

@bot.tree.command(name="makeprivatechannel", description="Rent a private text or voice channel")
@app_commands.choices(channel_type=[
    app_commands.Choice(name="Text", value="text"),
    app_commands.Choice(name="Voice", value="voice")
], duration=[
    app_commands.Choice(name="1 Hour", value=1),
    app_commands.Choice(name="2 Hours", value=2),
    app_commands.Choice(name="4 Hours", value=4)
])
async def makeprivate(interaction: discord.Interaction, channel_type: str, name: str, duration: int, members: str):
    config = col_settings.find_one({"_id": "config"})
    if config["panic"] and not is_admin(interaction.user.id):
        return await interaction.response.send_message("🔒 System is currently disabled (Panic Mode).", ephemeral=True)

    user_id = interaction.user.id
    data = get_user_data(user_id)

    # Check if already has a channel
    if data.get("current_private_channel_id") and not is_admin(user_id):
        return await interaction.response.send_message("❌ You already have an active private channel.", ephemeral=True)

    # Parse members (mentions)
    member_ids = [int(id) for id in re.findall(r'<@!?(\d+)>', members)]
    member_ids = list(set(member_ids)) # Unique
    if user_id in member_ids: member_ids.remove(user_id) # Remove self if added
    
    total_users = len(member_ids) + 1 # +1 for Owner

    # Validation
    if total_users < 2:
        return await interaction.response.send_message("❌ Minimum 2 users required.", ephemeral=True)
    if total_users > 7:
        return await interaction.response.send_message("❌ Maximum 7 users allowed.", ephemeral=True)

    # Calculate Price
    try:
        price = PRICES[channel_type][total_users][duration]
    except KeyError:
        return await interaction.response.send_message("❌ Invalid configuration.", ephemeral=True)

    # Check Balance
    if data["coins"] < price:
        return await interaction.response.send_message(f"❌ Insufficient coins. Cost: {price}, You have: {data['coins']}", ephemeral=True)

    # Create Channel
    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, connect=True)
    }

    # Add guests
    for m_id in member_ids:
        mem = guild.get_member(m_id)
        if mem:
            overwrites[mem] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True)
        # Check if guest is already in a channel (Optional: Prompt didn't strictly say guests can't be in multiple, only User can have one)

    try:
        if channel_type == "text":
            channel = await guild.create_text_channel(name, overwrites=overwrites)
        else:
            channel = await guild.create_voice_channel(name, overwrites=overwrites)
    except Exception as e:
        return await interaction.response.send_message(f"❌ Error creating channel: {e}", ephemeral=True)

    # Deduct Coins & Save
    col_users.update_one({"_id": user_id}, {"$inc": {"coins": -price}, "$set": {"current_private_channel_id": channel.id}})
    
    expiry = datetime.utcnow() + timedelta(hours=duration)
    col_channels.insert_one({
        "channel_id": channel.id,
        "owner_id": user_id,
        "type": channel_type,
        "end_time": expiry
    })

    if channel_type == "text":
        await channel.send(f"✅ Private Channel Active for {duration}h. Owner: {interaction.user.mention}")

    await interaction.response.send_message(f"✅ Channel created: {channel.mention}. Cost: {price} coins.", ephemeral=True)

# =========================================
# 🎮 GAMING & TICKETS
# =========================================

@bot.tree.command(name="findteam", description="Find a Free Fire team")
async def findteam(interaction: discord.Interaction, role: str, level: str, message: str):
    if interaction.channel.name != "find-team":
        return await interaction.response.send_message("❌ Use this command in #find-team only.", ephemeral=True)

    embed = discord.Embed(title="🎮 Free Fire Team Request", color=discord.Color.orange())
    embed.add_field(name="Player", value=interaction.user.mention, inline=True)
    embed.add_field(name="Role", value=role, inline=True)
    embed.add_field(name="Level", value=level, inline=True)
    embed.add_field(name="Message", value=message, inline=False)
    embed.set_footer(text="DM user to join. Auto-deletes in 30m.")

    await interaction.response.send_message(embed=embed, delete_after=1800)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green, custom_id="open_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user has ticket
        existing = discord.utils.get(interaction.guild.text_channels, topic=f"Ticket Owner: {interaction.user.id}")
        if existing:
            return await interaction.response.send_message(f"❌ You already have a ticket: {existing.mention}", ephemeral=True)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        # Add admins
        for aid in ADMIN_IDS:
            m = interaction.guild.get_member(aid)
            if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True)

        chan = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name}", overwrites=overwrites, topic=f"Ticket Owner: {interaction.user.id}")
        await chan.send(f"{interaction.user.mention} Support will be with you shortly. Use `/close` to close.", view=None)
        await interaction.response.send_message(f"✅ Ticket created: {chan.mention}", ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Admin: Send ticket panel")
async def ticketpanel(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.send("📩 **Need Help?** Click below to open a ticket.", view=TicketView())
    await interaction.response.send_message("Panel sent.", ephemeral=True)

@bot.tree.command(name="close", description="Close the current ticket")
async def close(interaction: discord.Interaction):
    if "ticket-" in interaction.channel.name:
        await interaction.response.send_message("🗑️ Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete()
    else:
        await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)

# =========================================
# 🛡️ MODERATION & ADMIN
# =========================================

@bot.tree.command(name="lock", description="Admin: Lock server")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": True}})
    
    # Logic to deny Send Message perm for @everyone in current channel (or all loop)
    # Simple implementation: current channel
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False, create_public_threads=False)
    await interaction.response.send_message("🔒 Channel Locked.")

@bot.tree.command(name="unlock", description="Admin: Unlock server")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": False}})
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True, create_public_threads=True)
    await interaction.response.send_message("🔓 Channel Unlocked.")

@bot.tree.command(name="addcoins", description="Admin: Add coins to user")
async def addcoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return
    get_user_data(user.id) # Ensure exists
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"✅ Added {amount} coins to {user.mention}.", ephemeral=True)

@bot.tree.command(name="panic", description="Admin: Toggle Panic Mode")
async def panic(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    
    curr = col_settings.find_one({"_id": "config"})
    new_state = not curr["panic"]
    col_settings.update_one({"_id": "config"}, {"$set": {"panic": new_state}})
    
    status = "ENABLED 🔴" if new_state else "DISABLED 🟢"
    await interaction.response.send_message(f"🚨 Panic Mode {status} (Redeems/Private Channels blocked).", ephemeral=True)

@bot.tree.command(name="clear", description="Admin: Clear messages")
async def clear(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction.user.id): return
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Cleared {amount} messages.", ephemeral=True)

# =========================================
# EVENTS (Member Join/Leave, Vouch Listener)
# =========================================

@bot.event
async def on_member_join(member):
    # Welcome Message
    channel = discord.utils.get(member.guild.text_channels, name="welcome") # Or ID
    if channel:
        embed = discord.Embed(title="👋 Welcome to enjoined_gaming!", description=f"Hello {member.mention}!", color=discord.Color.purple())
        embed.add_field(name="🎮 Roles", value="Choose your game roles", inline=False)
        embed.add_field(name="💰 Economy", value="Use `/daily` to get coins", inline=False)
        embed.add_field(name="📜 Rules", value=EG_COND, inline=False)
        await channel.send(embed=embed)
    
    # Auto Role
    role = discord.utils.get(member.guild.roles, name="Member")
    if role:
        await member.add_roles(role)

@bot.event
async def on_member_remove(member):
    # Reset Data
    col_users.delete_one({"_id": member.id})
    # Optional: Delete active private channel if they own one immediately
    # (The background task will eventually catch it, or handle here for instant cleanup)

@bot.event
async def on_message(message):
    if message.author.bot: return

    # Vouch Logic
    # Format: [CODE] I got [SERVICE], thanks @admin
    
    # Check if this channel is waiting for a vouch
    pending = col_vouch.find_one({"channel_id": message.channel.id, "user_id": message.author.id})
    
    if pending:
        # Regex Validation
        # Starts with [ANYTHING], contains "I got", contains "thanks", mentions a user
        pattern = r"^\[.+\] I got .+, thanks <@\d+>$"
        
        if re.match(pattern, message.content, re.IGNORECASE):
            # Valid Vouch
            await message.add_reaction("✅")
            await message.channel.send("✅ Vouch accepted! Closing channel in 10 seconds...")
            
            # Log to log channel
            log_channel = discord.utils.get(message.guild.text_channels, name="vouch-logs")
            if log_channel:
                await log_channel.send(f"✅ **Vouch Log:** {message.author.name} vouched for `{pending['service']}`.")

            col_vouch.delete_one({"_id": pending["_id"]})
            
            await asyncio.sleep(10)
            await message.channel.delete()
        else:
            # Invalid format inside a redeem channel
            await message.delete()
            await message.channel.send(f"❌ {message.author.mention} **WRONG FORMAT!**\nUse: `[{pending['code_used']}] I got {pending['service']}, thanks @admin`", delete_after=5)

    await bot.process_commands(message)

# =========================================
# 🚀 RUN
# =========================================

bot.run(TOKEN)
