import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
import aiohttp
from pymongo import MongoClient
import certifi

# --- KEEP ALIVE ---
app = discord.Client(intents=discord.Intents.default()) # Dummy for logic if needed
from flask import Flask
from threading import Thread

flask_app = Flask('')
@flask_app.route('/')
def home(): return "Tech4U Bot is 24/7!"
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
warns_col = db["warnings"]
vouch_col = db["vouch_permits"]
count_col = db["counting_data"] # New collection for counting

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

bot = MyBot()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/help | Tech4U"))
    print(f'✅ Logged in as {bot.user}')

# --- ON MESSAGE: COUNTING LOGIC & VOUCH MONITOR ---
@bot.event
async def on_message(message):
    if message.author.bot: return

    # 1. COUNTING SYSTEM
    guild_id = str(message.guild.id)
    c_data = count_col.find_one({"_id": guild_id})
    
    if c_data and message.channel.id == c_data.get("channel_id"):
        # Check if the message is a number
        if message.content.isdigit():
            input_num = int(message.content)
            current_count = c_data.get("count", 0)
            last_user = c_data.get("last_user_id")
            next_num = current_count + 1

            # Rule: Same user can't count twice
            if str(message.author.id) == last_user:
                count_col.update_one({"_id": guild_id}, {"$set": {"count": 0, "last_user_id": None}})
                await message.add_reaction("❌")
                return await message.channel.send(f"{message.author.mention} **RUINED IT AT {current_count}!!** Next number is **1**. You can't count twice in a row!")

            # Rule: Must be next number
            if input_num == next_num:
                count_col.update_one({"_id": guild_id}, {"$set": {"count": next_num, "last_user_id": str(message.author.id)}})
                await message.add_reaction("✅")
            else:
                count_col.update_one({"_id": guild_id}, {"$set": {"count": 0, "last_user_id": None}})
                await message.add_reaction("❌")
                await message.channel.send(f"{message.author.mention} **RUINED IT AT {current_count}!!** Next number is **1**. Wrong number!")

    # 2. VOUCH MONITOR (STRICT 1 MSG LIMIT)
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        user_v_data = vouch_col.find_one({"_id": uid})
        if user_v_data and user_v_data.get("permits", 0) > 0:
            vouch_col.update_one({"_id": uid}, {"$inc": {"permits": -1}})
            await message.add_reaction("✅")
            # Lock if no permits left
            if vouch_col.find_one({"_id": uid}).get("permits", 0) == 0:
                await message.channel.set_permissions(message.author, send_messages=False)
        else:
            try: await message.delete()
            except: pass

# --- ADMIN: SETUP COUNTING CHANNEL ---
@bot.tree.command(name="nub", description="Set the current channel as the counting channel (Admin Only)")
async def set_counting(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    guild_id = str(interaction.guild.id)
    count_col.update_one(
        {"_id": guild_id}, 
        {"$set": {"channel_id": interaction.channel.id, "count": 0, "last_user_id": None}}, 
        upsert=True
    )
    await interaction.response.send_message(f"✅ The counting channel has been set to {interaction.channel.mention}. Start with **1**!")

# --- ADMIN: ANNOUNCE ---
@bot.tree.command(name="announce", description="Send a professional announcement")
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    embed = discord.Embed(title=title, description=message.replace("\\n", "\n"), color=discord.Color.gold())
    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Sent!", ephemeral=True)

# --- ADMIN: ADD CODE ---
@bot.tree.command(name="addcode", description="Add account details")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    codes_col.update_one({"_id": code}, {"$set": {"service": service, "email": email, "password": password}}, upsert=True)
    await interaction.response.send_message(f"✅ Code `{code}` registered.", ephemeral=True)

# --- USER: REDEEM ---
@bot.tree.command(name="redeem", description="Redeem your code")
async def redeem(interaction: discord.Interaction, code: str):
    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid or used code!", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    try:
        guild = interaction.guild
        member = interaction.user
        is_youtube = "youtube" in item['service'].lower()

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=is_youtube, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        temp_chan = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
        await interaction.followup.send(f"✅ Success! Go to {temp_chan.mention}", ephemeral=True)

        if is_youtube:
            await temp_chan.send(f"{member.mention} ⚠️ **YouTube Premium Detected!**\nPlease **TYPE YOUR GMAIL** here.")
            def check(m): return m.author == member and m.channel == temp_chan
            try:
                msg = await bot.wait_for('message', check=check, timeout=300.0)
                await bot.get_channel(GMAIL_LOG_CHANNEL_ID).send(f"📬 **YT Request**\nUser: {member.mention}\nGMAIL: `{msg.content}`\nCode: `{code}`")
                await temp_chan.send("✅ Gmail received! Admin will process soon.")
            except asyncio.TimeoutError:
                await temp_chan.send("⏰ Timeout!")
        else:
            embed = discord.Embed(title="🎁 Details Delivered!", color=discord.Color.green())
            embed.add_field(name="Service", value=item['service'], inline=False)
            embed.add_field(name="Email", value=f"`{item['email']}`", inline=True)
            embed.add_field(name="Password", value=f"`{item['password']}`", inline=True)
            await temp_chan.send(content=member.mention, embed=embed)

        await temp_chan.send(f"📢 **VOUCH REQUIRED:** Copy & Paste this in <#{VOUCH_CHANNEL_ID}>:\n`{code} I got {item['service']}, thanks @admin`")
        await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(member, send_messages=True)
        vouch_col.update_one({"_id": str(member.id)}, {"$inc": {"permits": 1}}, upsert=True)

        await asyncio.sleep(600)
        await temp_chan.delete()

        user_vouch = vouch_col.find_one({"_id": str(member.id)})
        if user_vouch and user_vouch.get("permits", 0) > 0:
            warns_col.update_one({"_id": str(member.id)}, {"$inc": {"count": 1}}, upsert=True)
            w_data = warns_col.find_one({"_id": str(member.id)})
            await bot.get_channel(WARN_CHANNEL_ID).send(f"msg in vouches {member.mention}")
            if w_data['count'] >= 3: await member.ban(reason="No vouching")
    except Exception as e: print(e)

@bot.tree.command(name="help", description="How to use Tech4U")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U Help", color=discord.Color.blue())
    embed.description = "1️⃣ Get code from GP Link\n2️⃣ `/redeem` here\n3️⃣ Open private channel\n4️⃣ Vouch in #vouches"
    await interaction.response.send_message(embed=embed)

keep_alive()
bot.run(TOKEN)
