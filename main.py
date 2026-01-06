import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
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
def home(): return "Tech4U Master Bot Active!"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- 2. DATABASE SETUP ---
MONGO_URI = os.getenv("MONGO_URI")
ca = certifi.where()
cluster = MongoClient(MONGO_URI, tlsCAFile=ca, tlsAllowInvalidCertificates=True)
db = cluster["tech4u_database"]
codes_col, vouch_col, count_col, warns_col, bans_col = db["codes"], db["vouch_permits"], db["counting_data"], db["warnings"], db["temp_bans"]

# --- 3. CONFIGURATION (UPDATED IDs) ---
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = "https://discord.com/api/webhooks/1457635950942490645/fD3vFDv7IExZcZqEp6rLNd0cy1RM_Ccjv53o4Ne64HUhV5WRAmyKWpc7ph9J7lIMthD8"
REDEEM_LOG_ID = 1457623750475387136
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626
GMAIL_LOG_CHANNEL_ID = 1457609174350303324 
OWO_CHANNEL_ID = 1457943236982079678

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds, intents.members, intents.message_content = True, True, True
        super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        await self.tree.sync()
        self.unban_task.start()

    @tasks.loop(minutes=30)
    async def unban_task(self):
        now = datetime.utcnow()
        for ban in bans_col.find():
            if now >= ban["unban_at"]:
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
    await bot.change_presence(activity=discord.Game(name="/help | Tech4U"))
    print(f'✅ Tech4U Pro Online')

# --- TIMER LOGIC (WARNINGS & BAN) ---
async def start_vouch_timer(member, temp_channel):
    user_id = str(member.id)
    warn_chan = bot.get_channel(WARN_CHANNEL_ID)
    
    for i in range(1, 4):
        await asyncio.sleep(600) # 10 Minute Interval
        user_data = vouch_col.find_one({"_id": user_id})
        if user_data and user_data.get("permits", 0) > 0:
            if i == 1: await warn_chan.send(f"⚠️ **Reminder** {member.mention}\nYou have not posted your vouch yet. Please send your vouch in <#{VOUCH_CHANNEL_ID}>.")
            elif i == 2: await warn_chan.send(f"⚠️ **Second Warning** {member.mention}\nIt has been 20 minutes. Post in <#{VOUCH_CHANNEL_ID}> immediately.")
            elif i == 3:
                if member.guild_permissions.administrator:
                    await warn_chan.send(f"⚠️ {member.mention} Admin bypass for ban.")
                else:
                    await warn_chan.send(f"🚨 **Final Warning** {member.mention}\nYou are now **BANNED for 3 days** for ignoring the vouch requirement.")
                    unban_time = datetime.utcnow() + timedelta(days=3)
                    bans_col.update_one({"_id": member.id}, {"$set": {"unban_at": unban_time, "guild_id": member.guild.id}}, upsert=True)
                    try: await member.ban(reason="No vouch within 30m")
                    except: pass
    try: await temp_channel.delete()
    except: pass

# --- ON MESSAGE LOGIC ---
@bot.event
async def on_message(message):
    if message.author.bot: return

    # 1. OwO RULE
    if any(message.content.lower().startswith(c) for c in ["owo","hunt","battle","pray","sell","buy"]):
        if message.channel.id != OWO_CHANNEL_ID and not message.author.guild_permissions.administrator:
            await message.delete()
            return await message.channel.send(f"🚨 {message.author.mention} Use OwO in <#{OWO_CHANNEL_ID}>!", delete_after=5)

    # 2. COUNTING
    guild_id = str(message.guild.id)
    c_data = count_col.find_one({"_id": guild_id})
    if c_data and message.channel.id == c_data.get("channel_id") and message.content.isdigit():
        val, cur, last = int(message.content), c_data.get("count", 0), c_data.get("last_user_id")
        if str(message.author.id) == last or val != cur + 1:
            count_col.update_one({"_id": guild_id}, {"$set": {"count": 0, "last_user_id": None}})
            await message.add_reaction("❌")
            return await message.channel.send(f"❌ {message.author.mention} Reset to 1.")
        count_col.update_one({"_id": guild_id}, {"$set": {"count": val, "last_user_id": str(message.author.id)}})
        await message.add_reaction("✅")

    # 3. STRICT VOUCH CHECKER
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        user_v = vouch_col.find_one({"_id": uid})
        if user_v and user_v.get("permits", 0) > 0:
            # Check for EXACT match of the expected message
            expected = user_v.get("expected_msg")
            if message.content.strip().lower() == expected.lower():
                vouch_col.update_one({"_id": uid}, {"$inc": {"permits": -1}, "$set": {"expected_msg": ""}})
                await message.add_reaction("✅")
                await message.channel.send(f"✅ **Vouch Verified!** Thanks {message.author.mention}!", delete_after=10)
                if vouch_col.find_one({"_id": uid}).get("permits", 0) == 0:
                    await message.channel.set_permissions(message.author, send_messages=False)
            else:
                await message.delete()
                await message.channel.send(f"❌ {message.author.mention}, use the **EXACT** vouch format given in your private channel!", delete_after=10)
        else:
            try: await message.delete()
            except: pass

# --- COMMANDS ---
@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid code!", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    guild, member = interaction.guild, interaction.user
    is_yt = "youtube" in item['service'].lower()
    
    # Send Log to 1457623750475387136
    redeem_log = bot.get_channel(REDEEM_LOG_ID)
    if redeem_log: await redeem_log.send(f"The **[{code}]** have been use by {member.mention}")

    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  member: discord.PermissionOverwrite(view_channel=True, send_messages=is_yt, read_message_history=True),
                  guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)}
    temp = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
    await interaction.followup.send(f"✅ Success! Go to {temp.mention}")

    if is_yt:
        await temp.send(f"{member.mention} Type your **Gmail**:")
        try:
            msg = await bot.wait_for('message', check=lambda m: m.author == member and m.channel == temp, timeout=300.0)
            await bot.get_channel(GMAIL_LOG_CHANNEL_ID).send(f"📬 **YT Request**: {member.mention} | Gmail: `{msg.content}`")
            await temp.send("✅ Gmail sent to admin!")
        except: pass
    else:
        e = discord.Embed(title="🎁 Account Details", color=0x2ecc71)
        e.add_field(name="Service", value=item['service']).add_field(name="ID", value=f"`{item['email']}`").add_field(name="Pass", value=f"`{item['password']}`")
        await temp.send(embed=e)
    
    # STRICT VOUCH FORMAT
    expected_str = f"{code} I got {item['service']}, thanks @admin"
    await temp.send(f"📢 **VOUCH REQUIRED IN <#{VOUCH_CHANNEL_ID}>**:\n`{expected_str}`\n*Failure = 3 Day Ban!*")
    
    vouch_col.update_one({"_id": str(member.id)}, {"$inc": {"permits": 1}, "$set": {"expected_msg": expected_str}}, upsert=True)
    await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(member, send_messages=True)
    asyncio.create_task(start_vouch_timer(member, temp))

@bot.tree.command(name="addcode")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator: return
    codes_col.update_one({"_id": code}, {"$set": {"service": service, "email": email, "password": password}}, upsert=True)
    await interaction.response.send_message(f"✅ Code `{code}` registered.", ephemeral=True)

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="🛡️ Tech4U Help Center", color=0x3498db)
    e.description = f"1️⃣ Get code\n2️⃣ `/redeem` here\n3️⃣ Private channel\n4️⃣ Copy & Paste exactly in <#{VOUCH_CHANNEL_ID}>"
    await interaction.response.send_message(embed=e)

keep_alive()
bot.run(TOKEN)
