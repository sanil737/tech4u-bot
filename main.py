import discord
from discord import app_commands
from discord.ext import commands, tasks
import os, asyncio, aiohttp, certifi
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# --- 1. KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "enjoined_gaming Master Bot Online!"
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
codes_col, users_col, count_col, active_chans = db["codes"], db["users"], db["counting_data"], db["temp_channels"]
team_finder_col, vouch_col, warns_col, bans_col, limit_col = db["team_finder"], db["vouch_permits"], db["warnings"], db["temp_bans"], db["user_limits"]

# --- 3. CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
EG_COND = "EG cond - Respect all, vouch after use, and follow rules."
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626
GMAIL_LOG_ID = 1457609174350303324
REDEEM_LOG_ID = 1457623750475387136
OWO_CHANNEL_ID = 1457943236982079678
FIND_TEAM_CHANNEL_ID = 1459469475849175304 
WELCOME_CHANNEL_ID = 1459444229255200971

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
        self.unban_task.start()

    @tasks.loop(minutes=1)
    async def cleanup_loop(self):
        now = datetime.utcnow()
        for chan_data in active_chans.find({"expire_at": {"$lt": now}}):
            guild = self.get_guild(chan_data["guild_id"])
            if guild:
                channel = guild.get_channel(chan_data["_id"])
                if channel:
                    try: await channel.delete()
                    except: pass
            active_chans.delete_one({"_id": chan_data["_id"]})
            users_col.update_many({"in_temp_channel": chan_data["_id"]}, {"$set": {"in_temp_channel": None}})
        
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

    @tasks.loop(minutes=30)
    async def unban_task(self):
        now = datetime.utcnow()
        for ban in bans_col.find({"unban_at": {"$lt": now}}):
            guild = self.get_guild(ban["guild_id"])
            if guild:
                try:
                    user = await self.fetch_user(ban["_id"])
                    await guild.unban(user)
                    bans_col.delete_one({"_id": ban["_id"]})
                except: pass

bot = MyBot()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/help | EG cond"))
    print(f'✅ Bot is Ready')

# --- WELCOME ---
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        text = f"🎮 Welcome to **enjoined_gaming**, {member.mention}! 🎉\n\nDon’t forget to pick roles in <#1457635950942490645>\nUse `/help` to start! 😎"
        await channel.send(text)

# --- AUTO RULES ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    # OwO
    if any(message.content.lower().startswith(c) for c in ["owo","hunt","pray","buy"]):
        if message.channel.id != OWO_CHANNEL_ID and not message.author.guild_permissions.administrator:
            await message.delete()
            return await message.channel.send(f"🚨 {message.author.mention} OwO in <#{OWO_CHANNEL_ID}> only!", delete_after=5)
    # Vouch
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_delete({"_id": uid}):
            await message.add_reaction("✅")
            await message.channel.send(f"✅ Vouch Verified! Thanks {message.author.mention}!", delete_after=10)
            await message.channel.set_permissions(message.author, send_messages=False)
        else:
            if not message.author.guild_permissions.administrator: await message.delete()

# --- ADMIN COMMANDS ---
@bot.tree.command(name="lock")
async def lock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Channel Locked.")

@bot.tree.command(name="unlock")
async def unlock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Channel Unlocked.")

@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount: int):
    # Allowed for Admins and Moderators (Manage Messages permission)
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("❌ Moderator/Admin only.", ephemeral=True)
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Deleted {amount} messages.", ephemeral=True)

@bot.tree.command(name="givecond")
async def give_cond(interaction: discord.Interaction, amount: int, user: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"_id": str(user.id)}, {"$inc": {"balance": amount}}, upsert=True)
    await interaction.response.send_message(f"✅ Added Rs {amount} to {user.mention}")

# --- USER COMMANDS ---
@bot.tree.command(name="findteam")
async def find_team(interaction: discord.Interaction, role: str, level: str, message: str):
    if interaction.channel.id != FIND_TEAM_CHANNEL_ID:
        return await interaction.response.send_message("❌ Use in find-team channel.", ephemeral=True)
    e = discord.Embed(title="🟢 Free Fire Team Finder", color=discord.Color.green())
    e.add_field(name="User", value=interaction.user.mention).add_field(name="Role", value=role).add_field(name="Level", value=level)
    e.add_field(name="Message", value=message, inline=False)
    msg = await interaction.channel.send(embed=e)
    team_finder_col.insert_one({"_id": msg.id, "user_id": interaction.user.id, "guild_id": interaction.guild.id, "expire_at": datetime.utcnow() + timedelta(minutes=30)})
    await interaction.response.send_message("✅ Live!", ephemeral=True)

@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    uid = str(interaction.user.id)
    u_limit = limit_col.find_one({"_id": uid})
    if u_limit and (datetime.utcnow() - u_limit["last_redeem"]) < timedelta(days=1):
        return await interaction.response.send_message("❌ Wait 24h.", ephemeral=True)
    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
    
    limit_col.update_one({"_id": uid}, {"$set": {"last_redeem": datetime.utcnow()}}, upsert=True)
    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)}
    temp = await interaction.guild.create_text_channel(name=f"🎁-redeem-{interaction.user.name}", overwrites=overwrites)
    await temp.send(f"🎁 **Details:** {item['service']} | ID: {item['email']} | Pass: {item['password']}\n⏰ *Channel deletes in 30 mins.*")
    vouch_col.update_one({"_id": uid}, {"$set": {"permits": 1}}, upsert=True)
    await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(interaction.user, send_messages=True)
    await interaction.response.send_message(f"✅ Go to {temp.mention}", ephemeral=True)

keep_alive()
bot.run(TOKEN)
