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

# --- 1. KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "enjoined_gaming Bot Online 24/7!"
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
team_finder_col = db["team_finder"] # New for Free Fire posts

# --- 3. CONFIGURATION (IDs) ---
TOKEN = os.getenv("TOKEN")
EG_COND = "EG cond - Respect all, vouch after use, follow rules."
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626
GMAIL_LOG_ID = 1457609174350303324
OWO_CHANNEL_ID = 1457943236982079678
FIND_TEAM_CHANNEL_ID = 1459469475849175304 # Free Fire channel

PRICES = {
    "text": {1: 400, 2: 600, 3: 800},
    "voice": {1: 500, 2: 750, 3: 1000}
}

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds, intents.members, intents.message_content = True, True, True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        self.cleanup_loop.start()

    @tasks.loop(minutes=1)
    async def cleanup_loop(self):
        now = datetime.utcnow()
        # 1. Cleanup Private Channels
        for chan_data in active_chans.find({"expire_at": {"$lt": now}}):
            guild = self.get_guild(chan_data["guild_id"])
            if guild:
                channel = guild.get_channel(chan_data["_id"])
                if channel: await channel.delete()
            active_chans.delete_one({"_id": chan_data["_id"]})
            users_col.update_many({"in_temp_channel": chan_data["_id"]}, {"$set": {"in_temp_channel": None}})
        
        # 2. Cleanup Free Fire Posts (30 mins)
        for post in team_finder_col.find({"expire_at": {"$lt": now}}):
            guild = self.get_guild(post["guild_id"])
            if guild:
                channel = guild.get_channel(FIND_TEAM_CHANNEL_ID)
                if channel:
                    try:
                        msg = await channel.fetch_message(post["_id"])
                        await msg.delete()
                    except: pass
            team_finder_col.delete_one({"_id": post["_id"]})

bot = MyBot()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/help | EG cond"))
    print(f'✅ {bot.user.name} is online.')

# --- FREE FIRE TEAM FINDER COMMAND ---
@bot.tree.command(name="findteam", description="Find a Free Fire team (Free Fire role only)")
@app_commands.describe(role="Your role (Attacker, Support, etc.)", level="Your in-game level", message="Match details")
async def find_team(interaction: discord.Interaction, role: str, level: str, message: str):
    if interaction.channel.id != FIND_TEAM_CHANNEL_ID:
        return await interaction.response.send_message(f"❌ This command only works in <#{FIND_TEAM_CHANNEL_ID}>!", ephemeral=True)

    # Check for "Free Fire" role
    has_role = any(r.name == "Free Fire" for r in interaction.user.roles)
    if not has_role and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ You need the **Free Fire** role to use this!", ephemeral=True)

    # Check for existing post
    existing = team_finder_col.find_one({"user_id": interaction.user.id})
    if existing:
        return await interaction.response.send_message("❌ You already have an active team post! Wait for it to expire (30m).", ephemeral=True)

    embed = discord.Embed(title="🟢 Free Fire Team Finder", color=discord.Color.green())
    embed.add_field(name="👤 User", value=interaction.user.mention, inline=True)
    embed.add_field(name="🎯 Role", value=role, inline=True)
    embed.add_field(name="🏅 Level", value=level, inline=True)
    embed.add_field(name="💬 Message", value=message, inline=False)
    embed.set_footer(text="DM this user to join. Use /makeprivatechannel to form a room!")
    
    await interaction.response.send_message("✅ Your team post has been published!", ephemeral=True)
    post_msg = await interaction.channel.send(embed=embed)

    # Save to DB with 30 minute expiry
    expire = datetime.utcnow() + timedelta(minutes=30)
    team_finder_col.insert_one({
        "_id": post_msg.id,
        "user_id": interaction.user.id,
        "guild_id": interaction.guild.id,
        "expire_at": expire
    })

# --- PRIVATE CHANNEL SYSTEM ---
@bot.tree.command(name="makeprivatechannel", description="Create a paid room (Max 7 users)")
async def make_private(interaction: discord.Interaction, ctype: str, name: str, hours: int, 
                         u2: discord.Member=None, u3: discord.Member=None, u4: discord.Member=None, 
                         u5: discord.Member=None, u6: discord.Member=None, u7: discord.Member=None):
    uid = str(interaction.user.id)
    ctype = ctype.lower()
    if hours not in [1, 2, 3] or ctype not in ["text", "voice"]:
        return await interaction.response.send_message("❌ Invalid type or time (1, 2, 3h).", ephemeral=True)

    user_data = users_col.find_one({"_id": uid}) or {"balance": 0, "in_temp_channel": None}
    if user_data.get("in_temp_channel"):
        return await interaction.response.send_message("❌ You already have a private channel!", ephemeral=True)

    cost = PRICES[ctype][hours]
    if user_data.get("balance", 0) < cost:
        return await interaction.response.send_message(f"❌ Low balance! Needs Rs {cost}.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    expire = datetime.utcnow() + timedelta(hours=hours)
    
    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)}
    
    participants = [interaction.user, u2, u3, u4, u5, u6, u7]
    valid_members = [m for m in participants if m]

    if ctype == "text":
        new_chan = await interaction.guild.create_text_channel(name=name, overwrites=overwrites)
    else:
        new_chan = await interaction.guild.create_voice_channel(name=name, overwrites=overwrites)

    for m in valid_members:
        await new_chan.set_permissions(m, view_channel=True, send_messages=True, connect=True)
        users_col.update_one({"_id": str(m.id)}, {"$set": {"in_temp_channel": new_chan.id}}, upsert=True)

    users_col.update_one({"_id": uid}, {"$inc": {"balance": -cost}})
    active_chans.insert_one({"_id": new_chan.id, "owner_id": uid, "expire_at": expire, "guild_id": interaction.guild.id})
    
    await interaction.followup.send(f"✅ Channel {new_chan.mention} created!")

# --- STATUS & ADMIN ---
@bot.tree.command(name="status")
async def status(interaction: discord.Interaction):
    data = users_col.find_one({"_id": str(interaction.user.id)}) or {"balance": 0}
    await interaction.response.send_message(f"💰 Balance: Rs {data.get('balance', 0)}\nRules: {EG_COND}", ephemeral=True)

@bot.tree.command(name="givecond")
async def give_cond(interaction: discord.Interaction, amount: int, user: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"_id": str(user.id)}, {"$inc": {"balance": amount}}, upsert=True)
    await interaction.response.send_message(f"✅ Added Rs {amount} to {user.mention}")

# --- (MODERATION & OWO LOGIC CONTINUED) ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    # OwO Rule
    if any(message.content.lower().startswith(c) for c in ["owo","hunt","pray"]):
        if message.channel.id != OWO_CHANNEL_ID and not message.author.guild_permissions.administrator:
            await message.delete()
            return await message.channel.send(f"🚨 Use OwO in <#{OWO_CHANNEL_ID}>!", delete_after=5)

bot.run(TOKEN)
