import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import asyncio
import aiohttp
from pymongo import MongoClient
import certifi
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# --- 1. KEEP ALIVE (Railway/Render) ---
app = Flask('')
@app.route('/')
def home(): return "enjoined_gaming Master Bot Active!"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
def keep_alive():
    t = Thread(target=run_flask); t.start()

# --- 2. DATABASE SETUP ---
MONGO_URI = os.getenv("MONGO_URI")
ca = certifi.where()
cluster = MongoClient(MONGO_URI, tlsCAFile=ca, tlsAllowInvalidCertificates=True)
db = cluster["enjoined_gaming"]
codes_col = db["codes"]
vouch_col = db["vouch_permits"]
count_col = db["counting_data"]
warns_col = db["warnings"]
bans_col = db["temp_bans"]
users_col = db["users"]
active_chans = db["temp_channels"]

# --- 3. CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
EG_COND = "EG cond - Respect all members, vouch after use, and follow channel rules."
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626
GMAIL_LOG_ID = 1457609174350303324
OWO_CHANNEL_ID = 1457943236982079678

# --- PRICING DICTIONARY ---
PRICES = {
    "text": {1: 400, 2: 600, 3: 800},
    "voice": {1: 500, 2: 750, 3: 1000}
}

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        self.cleanup_loop.start()

    @tasks.loop(minutes=1)
    async def cleanup_loop(self):
        now = datetime.utcnow()
        for chan_data in active_chans.find({"expire_at": {"$lt": now}}):
            guild = self.get_guild(chan_data["guild_id"])
            if guild:
                channel = guild.get_channel(chan_data["_id"])
                if channel:
                    try: await channel.delete(reason="Private Channel Expired")
                    except: pass
            active_chans.delete_one({"_id": chan_data["_id"]})
            # Reset user status
            users_col.update_many({"in_temp_channel": chan_data["_id"]}, {"$set": {"in_temp_channel": None}})

bot = MyBot()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/help | EG cond"))
    print(f'✅ {bot.user.name} is online.')

# --- ON MESSAGE: OwO & COUNTING ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    # OwO Rule
    if any(message.content.lower().startswith(c) for c in ["owo","hunt","pray","buy","sell"]):
        if message.channel.id != OWO_CHANNEL_ID and not message.author.guild_permissions.administrator:
            await message.delete()
            return await message.channel.send(f"🚨 {message.author.mention} Use OwO in <#{OWO_CHANNEL_ID}> only!", delete_after=5)
    
    # Vouch Monitor
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_delete({"_id": uid}):
            await message.add_reaction("✅")
            await message.channel.send(f"✅ Vouch Verified! Thanks {message.author.mention}!", delete_after=10)
            await message.channel.set_permissions(message.author, send_messages=False)
        else:
            if not message.author.guild_permissions.administrator: await message.delete()

# --- ADMIN COMMANDS ---
@bot.tree.command(name="givecond", description="Give Rs balance to a user (Admin Only)")
async def give_cond(interaction: discord.Interaction, amount: int, user: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"_id": str(user.id)}, {"$inc": {"balance": amount}}, upsert=True)
    await interaction.response.send_message(f"✅ Added **Rs {amount}** to {user.mention}'s balance.")

@bot.tree.command(name="addcode")
async def add_code(interaction: discord.Interaction, code: str, value: int):
    if not interaction.user.guild_permissions.administrator: return
    codes_col.insert_one({"_id": code, "value": value})
    await interaction.response.send_message(f"✅ Code `{code}` (Rs {value}) added.")

# --- PRIVATE CHANNEL SYSTEM ---
@bot.tree.command(name="makeprivatechannel", description="Create a paid private room (Max 7 users)")
@app_commands.describe(ctype="text or voice", name="Channel Name", hours="1, 2, or 3")
async def make_private(interaction: discord.Interaction, ctype: str, name: str, hours: int, 
                         u2: discord.Member=None, u3: discord.Member=None, u4: discord.Member=None, 
                         u5: discord.Member=None, u6: discord.Member=None, u7: discord.Member=None):
    uid = str(interaction.user.id)
    ctype = ctype.lower()
    
    if ctype not in ["text", "voice"] or hours not in [1, 2, 3]:
        return await interaction.response.send_message("❌ Invalid type (text/voice) or time (1, 2, 3h).", ephemeral=True)

    # Check if user is already in a channel
    user_data = users_col.find_one({"_id": uid}) or {"balance": 0, "in_temp_channel": None}
    if user_data.get("in_temp_channel"):
        return await interaction.response.send_message("❌ You are already in a private channel! Wait for it to expire.", ephemeral=True)

    cost = PRICES[ctype][hours]
    if user_data.get("balance", 0) < cost:
        return await interaction.response.send_message(f"❌ Low Balance! Needs Rs {cost}. You have Rs {user_data.get('balance')}.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    # Permission setup
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True, speak=True),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }
    
    participants = [interaction.user, u2, u3, u4, u5, u6, u7]
    valid_members = [m for m in participants if m is not None]

    # Create Channel
    expire = datetime.utcnow() + timedelta(hours=hours)
    try:
        if ctype == "text":
            new_chan = await interaction.guild.create_text_channel(name=name, overwrites=overwrites)
        else:
            new_chan = await interaction.guild.create_voice_channel(name=name, overwrites=overwrites)

        # Add users
        for m in valid_members:
            await new_chan.set_permissions(m, view_channel=True, send_messages=True, connect=True)
            users_col.update_one({"_id": str(m.id)}, {"$set": {"in_temp_channel": new_chan.id}}, upsert=True)

        # Deduct balance
        users_col.update_one({"_id": uid}, {"$inc": {"balance": -cost}})
        
        active_chans.insert_one({
            "_id": new_chan.id, 
            "owner_id": uid, 
            "expire_at": expire, 
            "guild_id": interaction.guild.id
        })

        await interaction.followup.send(f"✅ Channel {new_chan.mention} created for {hours}h!")
        await new_chan.send(f"🏠 **Welcome to your Private Room!**\nOwner: {interaction.user.mention}\nRules: {EG_COND}\n⏰ **Deletes at:** {(expire + timedelta(hours=5, minutes=30)).strftime('%H:%M')} IST")
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

# --- STATUS COMMAND ---
@bot.tree.command(name="status", description="Check balance and active channel")
async def status(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    data = users_col.find_one({"_id": uid}) or {"balance": 0, "in_temp_channel": None}
    
    chan_info = "None"
    if data.get("in_temp_channel"):
        c = active_chans.find_one({"_id": data["in_temp_channel"]})
        if c:
            rem = c["expire_at"] - datetime.utcnow()
            mins = int(rem.total_seconds() / 60)
            chan_info = f"<#{c['_id']}> (Expires in {mins}m)"
        else:
            users_col.update_one({"_id": uid}, {"$set": {"in_temp_channel": None}})

    embed = discord.Embed(title=f"👤 {interaction.user.name} Status", color=discord.Color.green())
    embed.add_field(name="💰 Balance", value=f"Rs {data.get('balance', 0)}", inline=True)
    embed.add_field(name="🔐 Private Room", value=chan_info, inline=True)
    embed.set_footer(text=EG_COND)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- OTHER COMMANDS ---
@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    c_data = codes_col.find_one_and_delete({"_id": code})
    if not c_data: return await interaction.response.send_message("❌ Invalid code!", ephemeral=True)
    users_col.update_one({"_id": str(interaction.user.id)}, {"$inc": {"balance": c_data["value"]}}, upsert=True)
    await interaction.response.send_message(f"✅ Redeemed! Rs {c_data['value']} added to your balance.", ephemeral=True)

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="🎮 enjoined_gaming Bot", description=f"{EG_COND}", color=discord.Color.blue())
    e.add_field(name="Commands", value="`/makeprivatechannel` - Create room\n`/status` - Check balance\n`/redeem` - Add funds\n`/help` - This menu", inline=False)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Deleted {amount}", ephemeral=True)

@bot.tree.command(name="announce")
async def announce(interaction: discord.Interaction, game: str, message: str):
    if not interaction.user.guild_permissions.administrator: return
    e = discord.Embed(title=f"📢 {game} Announcement", description=message.replace("\\n", "\n"), color=discord.Color.gold())
    await interaction.channel.send(embed=e)
    await interaction.response.send_message("✅ Sent", ephemeral=True)

keep_alive()
bot.run(TOKEN)
