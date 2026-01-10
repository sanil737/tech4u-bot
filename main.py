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

# --- 1. KEEP ALIVE SERVER ---
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

# --- 3. CONFIGURATION (IDs) ---
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

# --- 4. WELCOME SYSTEM ---
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        welcome_text = (
            f"🎮 Welcome to **enjoined_gaming**, {member.mention}! 🎉\n\n"
            "Don’t forget to pick a game role to unlock your channels:\n\n"
            "🔥 Free Fire\n"
            "👑 Clash Royale\n"
            "👻 Among Us\n"
            "🧱 Roblox\n\n"
            "You can pick your role by reacting in <#1457635950942490645>\n\n"
            "Use `/help` to see all bot commands and start having fun! 😎"
        )
        await channel.send(welcome_text)

# --- 5. TIMER LOGIC (RESET PER CODE) ---
async def start_vouch_timer(member, temp_channel):
    user_id = str(member.id)
    warn_chan = bot.get_channel(WARN_CHANNEL_ID)
    for i in range(1, 4):
        await asyncio.sleep(600) # 10 mins
        # If permit exists, user hasn't vouched for THIS specific redeem
        permit = vouch_col.find_one({"_id": user_id})
        if permit:
            if i == 1: await warn_chan.send(f"⚠️ Reminder {member.mention}\nPlease vouch in <#{VOUCH_CHANNEL_ID}>.")
            elif i == 2: await warn_chan.send(f"⚠️ Second Warning {member.mention}\nVouch now in <#{VOUCH_CHANNEL_ID}>!")
            elif i == 3:
                if not member.guild_permissions.administrator:
                    await warn_chan.send(f"🚨 Final Warning {member.mention} BANNED for 3 days.")
                    unban_time = datetime.utcnow() + timedelta(days=3)
                    bans_col.update_one({"_id": member.id}, {"$set": {"unban_at": unban_time, "guild_id": member.guild.id}}, upsert=True)
                    try: await member.ban(reason="No vouch (30m)")
                    except: pass
    try: await temp_channel.delete()
    except: pass

# --- 6. AUTO RULES (OwO, Vouch) ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    # OwO Rule
    if any(message.content.lower().startswith(c) for c in ["owo","hunt","pray","buy"]):
        if message.channel.id != OWO_CHANNEL_ID and not message.author.guild_permissions.administrator:
            await message.delete()
            return await message.channel.send(f"🚨 {message.author.mention} Use OwO in <#{OWO_CHANNEL_ID}> only!", delete_after=5)
    # Vouch logic (User can write anything)
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_delete({"_id": uid}):
            await message.add_reaction("✅")
            await message.channel.send(f"✅ **Vouch Verified!** Thanks {message.author.mention}!", delete_after=10)
            await message.channel.set_permissions(message.author, send_messages=False)
        else:
            if not message.author.guild_permissions.administrator: await message.delete()

# --- 7. COMMANDS ---
@bot.tree.command(name="lock")
async def lock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Channel Locked.")

@bot.tree.command(name="unlock")
async def unlock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Channel Unlocked.")

@bot.tree.command(name="findteam")
async def find_team(interaction: discord.Interaction, role: str, level: str, message: str):
    if interaction.channel.id != FIND_TEAM_CHANNEL_ID:
        return await interaction.response.send_message("❌ Wrong channel.", ephemeral=True)
    e = discord.Embed(title="🟢 Free Fire Team Finder", color=discord.Color.green())
    e.add_field(name="User", value=interaction.user.mention).add_field(name="Role", value=role).add_field(name="Level", value=level)
    e.add_field(name="Message", value=message, inline=False)
    msg = await interaction.channel.send(embed=e)
    team_finder_col.insert_one({"_id": msg.id, "user_id": interaction.user.id, "guild_id": interaction.guild.id, "expire_at": datetime.utcnow() + timedelta(minutes=30)})
    await interaction.response.send_message("✅ Posted.", ephemeral=True)

@bot.tree.command(name="makeprivatechannel")
async def make_private(interaction: discord.Interaction, ctype: str, name: str, hours: int):
    uid = str(interaction.user.id)
    ctype = ctype.lower()
    if hours not in [1, 2, 3]: return await interaction.response.send_message("❌ Use 1, 2, or 3h.")
    user_data = users_col.find_one({"_id": uid}) or {"balance": 0, "in_temp_channel": None}
    if user_data.get("in_temp_channel"): return await interaction.response.send_message("❌ Already in a room.")
    cost = PRICES[ctype][hours]
    if user_data.get("balance", 0) < cost: return await interaction.response.send_message(f"❌ Needs Rs {cost}.")

    await interaction.response.defer(ephemeral=True)
    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)}
    
    if ctype == "text": new_chan = await interaction.guild.create_text_channel(name=name, overwrites=overwrites)
    else: new_chan = await interaction.guild.create_voice_channel(name=name, overwrites=overwrites)

    users_col.update_one({"_id": uid}, {"$inc": {"balance": -cost}, "$set": {"in_temp_channel": new_chan.id}}, upsert=True)
    active_chans.insert_one({"_id": new_chan.id, "owner_id": uid, "expire_at": datetime.utcnow() + timedelta(hours=hours), "guild_id": interaction.guild.id})
    await interaction.followup.send(f"✅ Success: {new_chan.mention}")

@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    uid = str(interaction.user.id)
    u_limit = limit_col.find_one({"_id": uid})
    if u_limit and (datetime.utcnow() - u_limit["last_redeem"]) < timedelta(days=1):
        return await interaction.response.send_message("❌ Wait 24h between redeems.", ephemeral=True)

    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    limit_col.update_one({"_id": uid}, {"$set": {"last_redeem": datetime.utcnow()}}, upsert=True)
    
    # Log Redeem
    log_chan = bot.get_channel(REDEEM_LOG_ID)
    if log_chan: await log_chan.send(f"**[{code}]** used by {interaction.user.mention}")

    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)}
    temp = await interaction.guild.create_text_channel(name=f"🎁-redeem-{interaction.user.name}", overwrites=overwrites)
    await temp.send(f"🎁 **Details:** {item['service']} | ID: {item['email']} | Pass: {item['password']}\n⏰ *Deletes in 30 mins.*")
    
    vouch_col.update_one({"_id": uid}, {"$set": {"permits": 1}}, upsert=True)
    await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(interaction.user, send_messages=True)
    asyncio.create_task(start_vouch_timer(interaction.user, temp))
    await interaction.followup.send(f"✅ Go to {temp.mention}")

@bot.tree.command(name="givecond")
async def give_cond(interaction: discord.Interaction, amount: int, user: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"_id": str(user.id)}, {"$inc": {"balance": amount}}, upsert=True)
    await interaction.response.send_message(f"✅ Added Rs {amount} to {user.mention}")

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="🛡️ enjoined_gaming Help", description=f"{EG_COND}", color=discord.Color.blue())
    e.add_field(name="Commands", value="`/redeem` | `/status` | `/findteam` | `/makeprivatechannel` | `/lock` | `/unlock`", inline=False)
    await interaction.response.send_message(embed=e)

keep_alive()
bot.run(TOKEN)
