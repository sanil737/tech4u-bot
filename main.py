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

# --- KEEP ALIVE ---
from flask import Flask
from threading import Thread
flask_app = Flask('')
@flask_app.route('/')
def home(): return "Tech4U Master Bot 24/7"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)
def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- DATABASE SETUP ---
MONGO_URI = os.getenv("MONGO_URI")
ca = certifi.where()
cluster = MongoClient(MONGO_URI, tlsCAFile=ca, tlsAllowInvalidCertificates=True)
db = cluster["tech4u_database"]
codes_col, vouch_col, count_col, warns_col, bans_col = db["codes"], db["vouch_permits"], db["counting_data"], db["warnings"], db["temp_bans"]

# --- CONFIG ---
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = "https://discord.com/api/webhooks/1457635950942490645/fD3vFDv7IExZcZqEp6rLNd0cy1RM_Ccjv53o4Ne64HUhV5WRAmyKWpc7ph9J7lIMthD8"
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626
GMAIL_LOG_CHANNEL_ID = 1457609174350303324 
OWO_CHANNEL_ID = 1457943236982079678

async def send_webhook_log(embed=None):
    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
            await webhook.send(embed=embed, username="Tech4U Logs")
    except: pass

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
    print(f'✅ Tech4U Online')

# --- TIMERS ---
async def start_vouch_timer(member, temp_channel):
    user_id = str(member.id)
    warn_chan = bot.get_channel(WARN_CHANNEL_ID)
    for i in range(1, 4):
        await asyncio.sleep(600)
        user_data = vouch_col.find_one({"_id": user_id})
        if user_data and user_data.get("permits", 0) > 0:
            if i == 1: await warn_chan.send(f"⚠️ **Reminder** {member.mention}\nYou have not posted your vouch yet. Please send your vouch in <#{VOUCH_CHANNEL_ID}>.")
            if i == 2: await warn_chan.send(f"⚠️ **Second Warning** {member.mention}\nIt has been 20 minutes. Post in <#{VOUCH_CHANNEL_ID}> now!")
            if i == 3:
                await warn_chan.send(f"🚨 **Final Warning** {member.mention}\nYou are now banned for 3 days for ignoring the vouch requirement.")
                unban_time = datetime.utcnow() + timedelta(days=3)
                bans_col.update_one({"_id": member.id}, {"$set": {"unban_at": unban_time, "guild_id": member.guild.id}}, upsert=True)
                try: await member.ban(reason="No vouch within 30m")
                except: pass
    try: await temp_channel.delete()
    except: pass

# --- AUTO-RULES ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    # OwO Rule
    if any(message.content.lower().startswith(c) for c in ["owo","hunt","battle","pray","sell","buy"]):
        if message.channel.id != OWO_CHANNEL_ID:
            await message.delete()
            return await message.channel.send(f"🚨 {message.author.mention} Use OwO in <#{OWO_CHANNEL_ID}>!", delete_after=5)
    # Counting
    guild_id = str(message.guild.id)
    c_data = count_col.find_one({"_id": guild_id})
    if c_data and message.channel.id == c_data.get("channel_id") and message.content.isdigit():
        val, cur, last = int(message.content), c_data.get("count", 0), c_data.get("last_user_id")
        if str(message.author.id) == last or val != cur + 1:
            count_col.update_one({"_id": guild_id}, {"$set": {"count": 0, "last_user_id": None}})
            await message.add_reaction("❌")
            return await message.channel.send(f"❌ {message.author.mention} ruined it at **{cur}**! Reset to 1.")
        count_col.update_one({"_id": guild_id}, {"$set": {"count": val, "last_user_id": str(message.author.id)}})
        await message.add_reaction("✅")
    # Vouch
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_update({"_id": uid, "permits": {"$gt": 0}}, {"$inc": {"permits": -1}}):
            await message.add_reaction("✅")
            if vouch_col.find_one({"_id": uid}).get("permits", 0) == 0:
                await message.channel.set_permissions(message.author, send_messages=False)
        else:
            try: await message.delete()
            except: pass

# --- LOCK & UNLOCK COMMANDS ---
@bot.tree.command(name="lock", description="Lock the current channel (Admin Only)")
async def lock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    await interaction.response.defer()
    overwrites = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrites.send_messages = False
    overwrites.send_messages_in_threads = False
    overwrites.create_public_threads = False
    overwrites.create_private_threads = False
    
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
    await interaction.followup.send(f"🔒 **This channel has been locked by {interaction.user.mention}**")

@bot.tree.command(name="unlock", description="Unlock the current channel (Admin Only)")
async def unlock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    await interaction.response.defer()
    overwrites = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrites.send_messages = True
    overwrites.send_messages_in_threads = True
    overwrites.create_public_threads = True
    overwrites.create_private_threads = True
    
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
    await interaction.followup.send(f"🔓 **This channel has been unlocked!**")

# --- OTHER ADMIN COMMANDS ---
@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🗑️ Deleted {len(deleted)} messages.")

@bot.tree.command(name="viewcodes")
async def viewcodes(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    all_c = codes_col.find()
    embed = discord.Embed(title="📦 Stock", color=0x9b59b6)
    count = 0
    for c in all_c:
        embed.add_field(name=f"Code: {c['_id']}", value=f"Service: {c['service']}\nID: `{c['email']}`\nPass: `{c['password']}`", inline=False)
        count += 1
    if count == 0: return await interaction.response.send_message("Empty.", ephemeral=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="addcode")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator: return
    codes_col.update_one({"_id": code}, {"$set": {"service": service, "email": email, "password": password}}, upsert=True)
    await interaction.response.send_message(f"✅ Code `{code}` added.", ephemeral=True)

@bot.tree.command(name="nub")
async def nub(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    count_col.update_one({"_id": str(interaction.guild.id)}, {"$set": {"channel_id": interaction.channel.id, "count": 0}}, upsert=True)
    await interaction.response.send_message(f"✅ Counting channel set.")

@bot.tree.command(name="announce")
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not interaction.user.guild_permissions.administrator: return
    embed = discord.Embed(title=title, description=message.replace("\\n", "\n"), color=discord.Color.gold())
    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Sent!", ephemeral=True)

# --- USER COMMANDS ---
@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid code!", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    guild, member = interaction.guild, interaction.user
    is_yt = "youtube" in item['service'].lower()
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  member: discord.PermissionOverwrite(view_channel=True, send_messages=is_yt, read_message_history=True),
                  guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)}
    temp = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
    await interaction.followup.send(f"✅ Success! Check {temp.mention}")
    if is_yt:
        await temp.send(f"{member.mention} Type Gmail:")
        try:
            msg = await bot.wait_for('message', check=lambda m: m.author == member and m.channel == temp, timeout=300.0)
            await bot.get_channel(GMAIL_LOG_CHANNEL_ID).send(f"📬 **YT Request**: {member.mention} | Gmail: `{msg.content}` | Code: `{code}`")
            await temp.send("✅ Sent to admin!")
        except: pass
    else:
        e = discord.Embed(title="🎁 Account Details", color=0x2ecc71)
        e.add_field(name="Service", value=item['service']).add_field(name="ID", value=f"`{item['email']}`").add_field(name="Pass", value=f"`{item['password']}`")
        e.description = "⏰ **Channel deletes in 30 mins.**"
        await temp.send(embed=e)
    await temp.send(f"📢 **VOUCH REQUIRED**:\n`{code} I got {item['service']}, thanks @admin`")
    vouch_col.update_one({"_id": str(member.id)}, {"$inc": {"permits": 1}}, upsert=True)
    await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(member, send_messages=True)
    asyncio.create_task(start_vouch_timer(member, temp))

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="🛡️ Tech4U Help Center", color=0x3498db)
    e.description = "1️⃣ Get code\n2️⃣ `/redeem` here\n3️⃣ Open private channel\n4️⃣ Vouch in #vouches\n⚠️ Failure to vouch in 30 mins = 3 Day Ban."
    await interaction.response.send_message(embed=e)

keep_alive()
bot.run(TOKEN)
