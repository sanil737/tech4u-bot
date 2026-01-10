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
def home(): return "enjoined_gaming Master Bot Active 24/7!"
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
codes_col, vouch_col, count_col, warns_col, bans_col = db["codes"], db["vouch_permits"], db["counting_data"], db["warnings"], db["temp_bans"]
limit_col, users_col, active_chans = db["user_limits"], db["users"], db["temp_channels"]

# --- 3. CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
EG_COND = "EG cond - Respect all, vouch after use, follow rules."
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626
GMAIL_LOG_ID = 1457609174350303324
OWO_CHANNEL_ID = 1457943236982079678
REDEEM_LOG_ID = 1457623750475387136

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

    @tasks.loop(minutes=30)
    async def unban_task(self):
        now = datetime.utcnow()
        for ban in bans_col.find({"unban_at": {"$lt": now}}):
            guild = self.get_guild(ban["guild_id"])
            if guild:
                try: await guild.unban(discord.Object(id=ban["_id"]))
                except: pass
            bans_col.delete_one({"_id": ban["_id"]})

bot = MyBot()

# --- TIMER LOGIC ---
async def start_vouch_timer(member, temp_channel):
    user_id = str(member.id)
    warn_chan = bot.get_channel(WARN_CHANNEL_ID)
    for i in range(1, 4):
        await asyncio.sleep(600)
        permit = vouch_col.find_one({"_id": user_id})
        if permit:
            if i == 1: await warn_chan.send(f"⚠️ **Reminder** {member.mention} Vouch in <#{VOUCH_CHANNEL_ID}>.")
            elif i == 2: await warn_chan.send(f"⚠️ **Second Warning** {member.mention} Vouch in <#{VOUCH_CHANNEL_ID}> now!")
            elif i == 3:
                if not member.guild_permissions.administrator:
                    await warn_chan.send(f"🚨 **Final Warning** {member.mention} BANNED for 3 days.")
                    bans_col.update_one({"_id": member.id}, {"$set": {"unban_at": datetime.utcnow() + timedelta(days=3), "guild_id": member.guild.id}}, upsert=True)
                    try: await member.ban(reason="Vouch Fail")
                    except: pass
    try: await temp_channel.delete()
    except: pass

# --- AUTO RULES ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    # OwO
    if any(message.content.lower().startswith(c) for c in ["owo","hunt","pray","buy"]):
        if message.channel.id != OWO_CHANNEL_ID and not message.author.guild_permissions.administrator:
            await message.delete()
            return await message.channel.send(f"🚨 {message.author.mention} Use OwO in <#{OWO_CHANNEL_ID}> only!", delete_after=5)
    # Vouch
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_delete({"_id": uid}):
            await message.add_reaction("✅")
            await message.channel.send(f"✅ Vouch Verified! Thanks {message.author.mention}!", delete_after=10)
            await message.channel.set_permissions(message.author, send_messages=False)
        else:
            if not message.author.guild_permissions.administrator: await message.delete()

# --- PRIVATE CHANNEL SYSTEM ---
@bot.tree.command(name="makeprivatechannel", description="Paid Room (2-7 Users)")
async def make_private(interaction: discord.Interaction, ctype: str, channel_name: str, hours: int, 
                         u2: discord.Member, u3: discord.Member=None, u4: discord.Member=None, 
                         u5: discord.Member=None, u6: discord.Member=None, u7: discord.Member=None):
    uid = str(interaction.user.id)
    ctype = ctype.lower()
    if ctype not in ["text", "voice"] or hours not in [1, 2, 3]:
        return await interaction.response.send_message("❌ Type: text/voice | Time: 1, 2, 3.", ephemeral=True)

    participants = [interaction.user, u2, u3, u4, u5, u6, u7]
    valid_members = [m for m in participants if m is not None]
    
    # Check if ANYONE in the list is already in a channel
    for m in valid_members:
        if users_col.find_one({"_id": str(m.id), "in_temp_channel": {"$ne": None}}):
            return await interaction.response.send_message(f"❌ {m.display_name} is already in a private channel!", ephemeral=True)

    user_data = users_col.find_one({"_id": uid}) or {"balance": 0}
    cost = PRICES[ctype][hours]
    if user_data.get("balance", 0) < cost:
        return await interaction.response.send_message(f"❌ Need Rs {cost}. You have Rs {user_data.get('balance', 0)}.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    expire = datetime.utcnow() + timedelta(hours=hours)
    
    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  interaction.guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)}

    if ctype == "text":
        new_chan = await interaction.guild.create_text_channel(name=channel_name, overwrites=overwrites)
    else:
        new_chan = await interaction.guild.create_voice_channel(name=channel_name, overwrites=overwrites)

    for m in valid_members:
        await new_chan.set_permissions(m, view_channel=True, send_messages=True, connect=True)
        users_col.update_one({"_id": str(m.id)}, {"$set": {"in_temp_channel": new_chan.id}}, upsert=True)

    users_col.update_one({"_id": uid}, {"$inc": {"balance": -cost}})
    active_chans.insert_one({"_id": new_chan.id, "owner_id": uid, "expire_at": expire, "guild_id": interaction.guild.id})
    
    await interaction.followup.send(f"✅ {new_chan.mention} created! Balance used: Rs {cost}")
    await new_chan.send(f"🏠 **Private Room Active!**\n{EG_COND}\n⏰ Deletes in {hours} hour(s).")

# --- CORE UTILITY ---
@bot.tree.command(name="givecond")
async def give_cond(interaction: discord.Interaction, amount: int, user: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"_id": str(user.id)}, {"$inc": {"balance": amount}}, upsert=True)
    await interaction.response.send_message(f"✅ Added Rs {amount} to {user.mention}")

@bot.tree.command(name="status")
async def status(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    data = users_col.find_one({"_id": uid}) or {"balance": 0, "in_temp_channel": None}
    limit = limit_col.find_one({"_id": uid})
    
    cd = "Ready"
    if limit and (datetime.utcnow() - limit["last_redeem"]) < timedelta(days=1):
        rem = timedelta(days=1) - (datetime.utcnow() - limit["last_redeem"])
        cd = f"{int(rem.total_seconds()//3600)}h remaining"

    embed = discord.Embed(title=f"👤 {interaction.user.name}", color=discord.Color.green())
    embed.add_field(name="💰 Balance", value=f"Rs {data.get('balance', 0)}")
    embed.add_field(name="⏰ Redeem Cooldown", value=cd)
    embed.add_field(name="🔐 In Private Room", value="Yes" if data.get("in_temp_channel") else "No")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    uid = str(interaction.user.id)
    # 24h check
    limit = limit_col.find_one({"_id": uid})
    if limit and (datetime.utcnow() - limit["last_redeem"]) < timedelta(days=1):
        return await interaction.response.send_message("❌ 1 code per day limit!", ephemeral=True)

    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid code!", ephemeral=True)
    
    # Check if code is balance or account
    if "value" in item:
        users_col.update_one({"_id": uid}, {"$inc": {"balance": item["value"]}}, upsert=True)
        return await interaction.response.send_message(f"✅ Rs {item['value']} added to your balance!", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    limit_col.update_one({"_id": uid}, {"$set": {"last_redeem": datetime.utcnow()}}, upsert=True)
    
    guild, member = interaction.guild, interaction.user
    log_chan = bot.get_channel(REDEEM_LOG_ID)
    if log_chan: await log_chan.send(f"**[{code}]** used by {member.mention}")

    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                  guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)}
    temp = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
    
    e = discord.Embed(title="🎁 Account Details", color=0x2ecc71)
    e.add_field(name="Service", value=item['service']).add_field(name="ID", value=f"`{item['email']}`").add_field(name="Pass", value=f"`{item['password']}`")
    e.description = "⏰ **Channel deletes in 30 mins. Save your IDP!**"
    await temp.send(embed=e)
    await temp.send(f"📢 **VOUCH REQUIRED IN <#{VOUCH_CHANNEL_ID}>**:\n`{code} I got {item['service']}, thanks @admin`")
    
    vouch_col.update_one({"_id": uid}, {"$set": {"permits": 1}}, upsert=True)
    await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(member, send_messages=True)
    asyncio.create_task(start_vouch_timer(member, temp))
    await interaction.followup.send(f"✅ Go to {temp.mention}")

@bot.tree.command(name="addaccount")
async def add_account(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator: return
    codes_col.update_one({"_id": code}, {"$set": {"service": service, "email": email, "password": password}}, upsert=True)
    await interaction.response.send_message(f"✅ Account Code `{code}` added.")

@bot.tree.command(name="announce")
async def announce(interaction: discord.Interaction, game: str, message: str):
    if not interaction.user.guild_permissions.administrator: return
    e = discord.Embed(title=f"📢 {game} Update", description=message.replace("\\n", "\n"), color=discord.Color.gold())
    await interaction.channel.send(embed=e)
    await interaction.response.send_message("✅ Sent", ephemeral=True)

keep_alive()
bot.run(TOKEN)
