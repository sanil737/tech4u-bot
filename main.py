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
def home(): return "Tech4U Bot 24/7 Active!"
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
codes_col = db["codes"]
vouch_col = db["vouch_permits"]
count_col = db["counting_data"]
bans_col = db["temp_bans"]

# --- CONFIG ---
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = "https://discord.com/api/webhooks/1457635950942490645/fD3vFDv7IExZcZqEp6rLNd0cy1RM_Ccjv53o4Ne64HUhV5WRAmyKWpc7ph9J7lIMthD8"
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626
GMAIL_LOG_CHANNEL_ID = 1457609174350303324 

async def send_webhook_log(embed=None):
    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
            await webhook.send(embed=embed, username="Tech4U Logs")
    except: pass

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
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
    print(f'✅ Logged in as {bot.user}')

# --- TIMER LOGIC FOR WARNINGS & DELETION ---
async def start_vouch_logic(member, temp_channel):
    user_id = str(member.id)
    warn_chan = bot.get_channel(WARN_CHANNEL_ID)

    # 1. 10 MINUTES (1st Warning)
    await asyncio.sleep(600)
    user_data = vouch_col.find_one({"_id": user_id})
    if user_data and user_data.get("permits", 0) > 0:
        await warn_chan.send(f"⚠️ **Reminder** {member.mention}\nYou have not posted your vouch yet.\nPlease send your vouch in <#{VOUCH_CHANNEL_ID}>.")

        # 2. 20 MINUTES (2nd Warning)
        await asyncio.sleep(600)
        user_data = vouch_col.find_one({"_id": user_id})
        if user_data and user_data.get("permits", 0) > 0:
            await warn_chan.send(f"⚠️ **Second Warning** {member.mention}\nIt has been 20 minutes and you still have not posted your vouch.\nPost in <#{VOUCH_CHANNEL_ID}> immediately.")

            # 3. 30 MINUTES (Final Ban)
            await asyncio.sleep(600)
            user_data = vouch_col.find_one({"_id": user_id})
            if user_data and user_data.get("permits", 0) > 0:
                await warn_chan.send(f"🚨 **Final Warning** {member.mention}\nYou did not post a vouch within 30 minutes.\nYou are now banned for 3 days.")
                unban_time = datetime.utcnow() + timedelta(days=3)
                bans_col.update_one({"_id": member.id}, {"$set": {"unban_at": unban_time, "guild_id": member.guild.id}}, upsert=True)
                try: await member.ban(reason="Vouch requirement ignored (30 mins)")
                except: pass
    
    # ALWAYS DELETE CHANNEL AFTER 30 MINS (No matter what)
    try: await temp_channel.delete()
    except: pass

# --- ON MESSAGE: OwO RULE + COUNTING + VOUCH ---
@bot.event
async def on_message(message):
    if message.author.bot: return

    # 1. OwO RULE
    owo_cmds = ["owo", "hunt", "battle", "pray", "sell", "buy"]
    content_lower = message.content.lower()
    if any(content_lower.startswith(cmd) for cmd in owo_cmds):
        # If channel name DOES NOT contain "owo"
        if "owo" not in message.channel.name.lower():
            await message.delete()
            return await message.channel.send(f"🚨 {message.author.mention}\nYou can’t use OwO commands outside #owo channels.", delete_after=10)

    # 2. COUNTING GAME
    guild_id = str(message.guild.id)
    c_data = count_col.find_one({"_id": guild_id})
    if c_data and message.channel.id == c_data.get("channel_id"):
        if message.content.isdigit():
            val, current, last = int(message.content), c_data.get("count", 0), c_data.get("last_user_id")
            if str(message.author.id) == last or val != current + 1:
                count_col.update_one({"_id": guild_id}, {"$set": {"count": 0, "last_user_id": None}})
                await message.add_reaction("❌")
                return await message.channel.send(f"{message.author.mention} **RUINED IT!** Resetting to 1.")
            count_col.update_one({"_id": guild_id}, {"$set": {"count": val, "last_user_id": str(message.author.id)}})
            await message.add_reaction("✅")

    # 3. VOUCH MONITOR
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_update({"_id": uid, "permits": {"$gt": 0}}, {"$inc": {"permits": -1}}):
            await message.add_reaction("✅")
            # Close access after vouch
            new_v = vouch_col.find_one({"_id": uid})
            if new_v.get("permits", 0) == 0:
                await message.channel.set_permissions(message.author, send_messages=False)
        else:
            try: await message.delete()
            except: pass

# --- COMMANDS ---
@bot.tree.command(name="nub", description="Setup Counting Channel")
async def nub(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    count_col.update_one({"_id": str(interaction.guild.id)}, {"$set": {"channel_id": interaction.channel.id, "count": 0}}, upsert=True)
    await interaction.response.send_message(f"✅ Counting channel set to {interaction.channel.mention}")

@bot.tree.command(name="addcode")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator: return
    codes_col.update_one({"_id": code}, {"$set": {"service": service, "email": email, "password": password}}, upsert=True)
    await interaction.response.send_message(f"✅ Code `{code}` registered.", ephemeral=True)

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
    
    temp_chan = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
    await interaction.followup.send(f"✅ Success! Go to {temp_chan.mention}")

    if is_yt:
        await temp_chan.send(f"{member.mention} Type your **Gmail** here.")
        try:
            msg = await bot.wait_for('message', check=lambda m: m.author == member and m.channel == temp_chan, timeout=300.0)
            await bot.get_channel(GMAIL_LOG_CHANNEL_ID).send(f"📬 **YT Request**: {member.mention} | Gmail: `{msg.content}`")
            await temp_chan.send("✅ Received! Admin will upgrade you soon.")
        except: pass
    else:
        embed = discord.Embed(title="🎁 Account Details", color=discord.Color.green())
        embed.add_field(name="Service", value=item['service']).add_field(name="Email", value=f"`{item['email']}`").add_field(name="Pass", value=f"`{item['password']}`")
        embed.description = "⏰ **This channel will delete in 30 minutes.**"
        await temp_chan.send(embed=embed)

    v_msg = f"`{code} I got {item['service']}, thanks @admin`"
    await temp_chan.send(f"📢 **VOUCH REQUIRED IN <#{VOUCH_CHANNEL_ID}>**:\n{v_msg}\n*Failure = 3 Day Ban!*")
    
    vouch_col.update_one({"_id": str(member.id)}, {"$inc": {"permits": 1}}, upsert=True)
    await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(member, send_messages=True)
    asyncio.create_task(start_vouch_logic(member, temp_chan))

@bot.tree.command(name="announce")
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not interaction.user.guild_permissions.administrator: return
    embed = discord.Embed(title=title, description=message.replace("\\n", "\n"), color=discord.Color.gold())
    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Sent!", ephemeral=True)

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U Help Center", color=discord.Color.blue())
    embed.description = "1️⃣ Get code from GP Link\n2️⃣ `/redeem` here\n3️⃣ Open private channel\n4️⃣ Vouch in #vouches (Required!)\n⚠️ Failure to vouch in 30 mins = 3 Day Ban."
    await interaction.response.send_message(embed=embed)

keep_alive()
bot.run(TOKEN)
