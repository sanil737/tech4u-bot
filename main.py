import discord
from discord import app_commands
from discord.ext import commands, tasks
import os, asyncio, random, certifi, aiohttp
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# --- 1. KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "enjoined_gaming God Bot Active!"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
def keep_alive():
    t = Thread(target=run_flask); t.daemon = True; t.start()

# --- 2. DATABASE ---
MONGO_URI = os.getenv("MONGO_URI")
cluster = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = cluster["enjoined_gaming"]
codes_col, users_col, active_chans = db["codes"], db["users"], db["temp_channels"]
vouch_col, warns_col, bans_col, team_finder_col = db["vouch_permits"], db["warnings"], db["temp_bans"], db["team_finder"]
settings_col, ticket_col = db["bot_settings"], db["tickets"]

# --- 3. CONFIG ---
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [986251574982606888, 1458812527055212585]
EG_COND = "📜 **EG Cond**: Respect all | Vouch after use | Follow rules"
WELCOME_ID = 1459444229255200971
FIND_TEAM_ID = 1459469475849175304
VOUCH_ID = 1459448284530610288
WARN_ID = 1459448651704303667
REDEEM_LOG_ID = 1459556690536960100
GMAIL_LOG_ID = 1457609174350303324
CATEGORY_ID = 1459557142850830489
REDEEM_USED_LOG_ID = 1457623750475387136

PRICES = {
    "text": {2: {1:400,2:700,4:1200},3:{1:500,2:900,4:1500},4:{1:600,2:1100,4:1800},5:{1:750,2:1300,4:2100},6:{1:900,2:1500,4:2500},7:{1:1050,2:1700,4:2800}},
    "voice": {2:{1:500,2:900,4:1500},3:{1:650,2:1100,4:1800},4:{1:800,2:1400,4:2300},5:{1:1000,2:1800,4:2900},6:{1:1200,2:2100,4:3400},7:{1:1400,2:2400,4:3900}}
}

# --- HELPERS ---
async def is_admin(interaction):
    return interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.administrator

def get_room_price(ctype, users, hours):
    users = max(2, min(users, 7))
    hours = hours if hours in [1,2,4] else 1
    return PRICES[ctype][users][hours]

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=".", intents=intents)
    async def setup_hook(self):
        await self.tree.sync()
        self.cleanup_loop.start()
        self.unban_loop.start()

    @tasks.loop(minutes=1)
    async def cleanup_loop(self):
        now = datetime.utcnow()
        for chan in active_chans.find({"expire_at":{"$lt":now}}):
            g = self.get_guild(chan["guild_id"])
            if g:
                c = g.get_channel(chan["_id"])
                if c: await c.delete()
            active_chans.delete_one({"_id":chan["_id"]})
            users_col.update_many({"in_room":chan["_id"]},{"$set":{"in_room":None}})
        for post in team_finder_col.find({"expire_at":{"$lt":now}}):
            g = self.get_guild(post["guild_id"])
            if g:
                ch = g.get_channel(FIND_TEAM_ID)
                if ch: 
                    try: m = await ch.fetch_message(post["_id"]); await m.delete()
                    except: pass
            team_finder_col.delete_one({"_id":post["_id"]})

    @tasks.loop(minutes=30)
    async def unban_loop(self):
        now = datetime.utcnow()
        for ban in bans_col.find({"unban_at": {"$lt": now}}):
            g = self.get_guild(ban["guild_id"])
            if g:
                try: u = await self.fetch_user(ban["_id"]); await g.unban(u)
                except: pass
            bans_col.delete_one({"_id": ban["_id"]})

bot = MyBot()

@bot.event
async def on_ready(): print(f"✅ God Bot Ready")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_ID)
    if ch: await ch.send(f"🎮 Welcome to **enjoined_gaming**, {member.mention}! 🎉\nDon’t forget to pick roles in <#1457635950942490645>\nUse `/help` to start! 😎")

@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.content.lower() == ".daily":
        uid = str(message.author.id)
        data = users_col.find_one({"_id":uid}) or {"balance":0,"last":datetime.min}
        if datetime.utcnow() - data.get("last",datetime.min) > timedelta(days=1):
            users_col.update_one({"_id":uid},{"$inc":{"balance":100},"$set":{"last":datetime.utcnow()}},upsert=True)
            await message.channel.send(f"✅ {message.author.mention}, you received **100 credits**!")
        else: await message.channel.send("⏳ Claim in 24h")
    if message.channel.id == VOUCH_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_delete({"_id": uid}):
            await message.add_reaction("✅")
            await message.channel.set_permissions(message.author, send_messages=False)
        elif not await is_admin(await bot.get_context(message)): await message.delete()
    await bot.process_commands(message)

# --- COMMANDS ---
@bot.tree.command(name="lock")
async def lock(interaction: discord.Interaction):
    if not await is_admin(interaction): return
    target = interaction.guild.default_role
    await interaction.channel.set_permissions(target, send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    await interaction.response.send_message("🔒 Channel Locked.")

@bot.tree.command(name="unlock")
async def unlock(interaction: discord.Interaction):
    if not await is_admin(interaction): return
    target = interaction.guild.default_role
    await interaction.channel.set_permissions(target, send_messages=True, send_messages_in_threads=True, create_public_threads=True, create_private_threads=True)
    await interaction.response.send_message("🔓 Channel Unlocked.")

@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount: int):
    if not (interaction.user.guild_permissions.manage_messages or await is_admin(interaction)): return
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted {amount} messages")

@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    uid = str(interaction.user.id)
    u_data = users_col.find_one({"_id": uid})
    if u_data and (datetime.utcnow() - u_data.get("last_red", datetime.min)) < timedelta(days=1):
        return await interaction.response.send_message("❌ One code per 24h.", ephemeral=True)
    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    users_col.update_one({"_id": uid}, {"$set": {"last_red": datetime.utcnow()}}, upsert=True)
    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)}
    temp = await interaction.guild.create_text_channel(name=f"🎁-{interaction.user.name}", overwrites=overwrites, category=bot.get_channel(CATEGORY_ID))
    e = discord.Embed(title="🎁 Account Details", color=0x2ecc71); e.add_field(name="Svc", value=item['service']).add_field(name="ID", value=item['email']).add_field(name="Pass", value=item['password'])
    e.description = "⏰ Channel deletes in 30 mins."
    await temp.send(content=interaction.user.mention, embed=e)
    vouch_col.update_one({"_id": uid}, {"$set": {"active": True}}, upsert=True)
    await bot.get_channel(VOUCH_ID).set_permissions(interaction.user, send_messages=True)
    await interaction.followup.send(f"✅ Success! Go to {temp.mention}")
    await asyncio.sleep(1800); await temp.delete()

@bot.tree.command(name="addcode")
async def addcode(interaction: discord.Interaction, code:str, service:str, email:str, password:str):
    if not await is_admin(interaction): return
    codes_col.update_one({"_id":code}, {"$set":{"service":service,"email":email,"password":password}}, upsert=True)
    await interaction.response.send_message(f"✅ Added {code}", ephemeral=True)

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="🛡️ enjoined_gaming Help", description=f"{EG_COND}", color=discord.Color.blue())
    e.add_field(name="User", value="`/redeem` | `/status` | `/findteam` | `/makeprivatechannel`", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

keep_alive()
bot.run(TOKEN)
