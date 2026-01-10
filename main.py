import discord
from discord import app_commands
from discord.ext import commands, tasks
import os, asyncio, random, certifi
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
    Thread(target=run_flask).start()

# --- 2. DATABASE SETUP ---
MONGO_URI = os.getenv("MONGO_URI")
ca = certifi.where()
cluster = MongoClient(MONGO_URI, tlsCAFile=ca, tlsAllowInvalidCertificates=True)
db = cluster["enjoined_gaming"]
codes_col, users_col, active_chans = db["codes"], db["users"], db["temp_channels"]
vouch_col, warns_col, bans_col, team_finder_col = db["vouch_permits"], db["warnings"], db["temp_bans"], db["team_finder"]
giveaway_col, settings_col, ticket_col = db["giveaways"], db["bot_settings"], db["tickets"]

# --- 3. CONFIG ---
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [986251574982606888, 1458812527055212585]
EG_COND = "EG cond - Respect all, vouch after use, and follow rules."
WELCOME_ID = 1459444229255200971
FIND_TEAM_ID = 1459469475849175304
VOUCH_ID = 1459448284530610288
REDEEM_LOG_ID = 1459556690536960100
WARN_ID = 1459448651704303667
GMAIL_LOG_ID = 1459448956580003840
CATEGORY_ID = 1459557142850830489

PRICES = {
    "text": {2: {1:400,2:700,4:1200},3:{1:500,2:900,4:1500},4:{1:600,2:1100,4:1800},5:{1:750,2:1300,4:2100},6:{1:900,2:1500,4:2500},7:{1:1050,2:1700,4:2800}},
    "voice": {2:{1:500,2:900,4:1500},3:{1:650,2:1100,4:1800},4:{1:800,2:1400,4:2300},5:{1:1000,2:1800,4:2900},6:{1:1200,2:2100,4:3400},7:{1:1400,2:2400,4:3900}}
}

# --- HELPERS ---
async def is_admin(interaction: discord.Interaction):
    return interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.administrator

def get_room_price(ctype, users, hours):
    users = max(2, min(users, 7))
    hours = hours if hours in [1,2,4] else 1
    return PRICES[ctype][users][hours]

# --- TICKET UI ---
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if ticket_col.find_one({"owner": interaction.user.id, "status":"open"}):
            return await interaction.response.send_message("❌ You already have a ticket!", ephemeral=True)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        chan = await interaction.guild.create_text_channel(name=f"ticket-{interaction.user.name}", overwrites=overwrites, category=interaction.channel.category)
        ticket_col.insert_one({"_id": chan.id, "owner": interaction.user.id, "status":"open"})
        await chan.send(f"Welcome {interaction.user.mention}! Support will be here shortly. Use `/close` to end.")
        await interaction.response.send_message(f"✅ Ticket created: {chan.mention}", ephemeral=True)

# --- GIVEAWAY UI ---
class GiveawayView(discord.ui.View):
    def __init__(self, g_id):
        super().__init__(timeout=None)
        self.g_id = g_id
    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.success, custom_id="join_g")
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_col.update_one({"_id": self.g_id}, {"$addToSet":{"participants":interaction.user.id}})
        await interaction.response.send_message("✅ You joined the giveaway!", ephemeral=True)

# --- BOT CLASS ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=".", intents=intents)
    async def setup_hook(self):
        await self.tree.sync()
        self.cleanup_loop.start()
    @tasks.loop(minutes=1)
    async def cleanup_loop(self):
        now = datetime.utcnow()
        # Cleanup private channels
        for chan in active_chans.find({"expire_at":{"$lt":now}}):
            g = self.get_guild(chan["guild_id"])
            if g:
                c = g.get_channel(chan["_id"])
                if c: await c.delete()
            active_chans.delete_one({"_id":chan["_id"]})
            users_col.update_many({"in_room":chan["_id"]},{"$set":{"in_room":None}})
        # Cleanup team posts
        for post in team_finder_col.find({"expire_at":{"$lt":now}}):
            g = self.get_guild(post["guild_id"])
            if g:
                ch = g.get_channel(FIND_TEAM_ID)
                if ch:
                    try: m = await ch.fetch_message(post["_id"]); await m.delete()
                    except: pass
            team_finder_col.delete_one({"_id":post["_id"]})

bot = MyBot()

# --- EVENTS ---
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/help | Tech4U"))
    print("✅ Bot Ready")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_ID)
    if ch: await ch.send(f"🎮 Welcome to **enjoined_gaming**, {member.mention}!\nDon’t forget to pick a role. Use `/help` to start! 😎")

@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.content.lower() == ".daily":
        ctx = await bot.get_context(message)
        await daily_logic(ctx)
    # Vouch logic
    if message.channel.id == VOUCH_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_delete({"_id": uid}):
            if "i got" in message.content.lower() and "@admin" in message.content.lower():
                await message.add_reaction("✅")
                await message.channel.send(f"✅ Vouch verified! Thanks {message.author.mention}")
                await message.channel.set_permissions(message.author, send_messages=False)
            else:
                await message.delete()
                await message.channel.send(f"❌ {message.author.mention}, use format: `[CODE] I got [ITEM], thanks @admin`", delete_after=5)
        elif message.author.id not in ADMIN_IDS: await message.delete()
    await bot.process_commands(message)

# --- DAILY LOGIC ---
async def daily_logic(interaction):
    uid = str(interaction.user.id)
    now = datetime.utcnow()
    data = users_col.find_one({"_id":uid}) or {"balance":0,"last_daily":datetime.min,"streak":0}
    if now - data.get("last_daily",datetime.min) > timedelta(days=1):
        streak = data.get("streak",0)+1 if now - data.get("last_daily",datetime.min) < timedelta(days=2) else 1
        reward = 100 + (streak*10) if streak<7 else 300
        users_col.update_one({"_id":uid},{"$inc":{"balance":reward},"$set":{"last_daily":now,"streak":streak}},upsert=True)
        msg = f"✅ You received **{reward} credits**! (Streak: {streak} days)"
        if hasattr(interaction,'response'): await interaction.response.send_message(msg)
        else: await interaction.channel.send(msg)
    else:
        msg = "⏳ Already claimed today! Come back in 24h."
        if hasattr(interaction,'response'): await interaction.response.send_message(msg,ephemeral=True)
        else: await interaction.channel.send(msg)

# --- TIMER FOR VOUCH ---
async def start_vouch_logic(member, temp_chan):
    for i in range(1,4):
        await asyncio.sleep(600)
        if vouch_col.find_one({"_id":str(member.id)}):
            warn_chan = bot.get_channel(WARN_ID)
            if i==1: await warn_chan.send(f"⚠️ Reminder {member.mention} vouch in <#{VOUCH_ID}>.")
            if i==2: await warn_chan.send(f"⚠️ Second Warning {member.mention} vouch now!")
            if i==3 and not member.guild_permissions.administrator:
                unban_at = datetime.utcnow()+timedelta(days=3)
                bans_col.update_one({"_id":member.id},{"$set":{"unban_at":unban_at,"guild_id":member.guild.id}},upsert=True)
                await member.ban(reason="No Vouch")
    try: await temp_chan.delete()
    except: pass

# --- SLASH COMMANDS ---
@bot.tree.command(name="daily")
async def daily_slash(interaction: discord.Interaction):
    await daily_logic(interaction)

@bot.tree.command(name="status")
async def status(interaction: discord.Interaction):
    d = users_col.find_one({"_id":str(interaction.user.id)}) or {"balance":0,"streak":0}
    await interaction.response.send_message(f"💰 Balance: Rs {d['balance']}\n🔥 Streak: {d['streak']} days\n🛡️ {EG_COND}", ephemeral=True)

@bot.tree.command(name="addcode")
async def add_code(interaction: discord.Interaction, code:str, service:str, email:str, password:str):
    if not await is_admin(interaction): return
    codes_col.update_one({"_id":code},{"$set":{"service":service,"email":email,"password":password}},upsert=True)
    await interaction.response.send_message(f"✅ Code `{code}` added.",ephemeral=True)

@bot.tree.command(name="addcoins")
async def add_coins(interaction: discord.Interaction, user:discord.Member, amount:int):
    if not await is_admin(interaction): return
    users_col.update_one({"_id":str(user.id)},{"$inc":{"balance":amount}},upsert=True)
    await interaction.response.send_message(f"✅ Added Rs {amount} to {user.mention}",ephemeral=True)

@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount:int):
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.id in ADMIN_IDS): return
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Deleted {amount} messages", ephemeral=True)

@bot.tree.command(name="makeprivatechannel")
async def make_private(interaction: discord.Interaction, ctype:str, name:str, hours:int, u2:discord.Member=None, u3:discord.Member=None,u4:discord.Member=None,u5:discord.Member=None,u6:discord.Member=None,u7:discord.Member=None):
    uid = str(interaction.user.id)
    m_list = [m for m in [interaction.user,u2,u3,u4,u5,u6,u7] if m]
    price = get_room_price(ctype,len(m_list),hours)
    u_data = users_col.find_one({"_id":uid}) or {"balance":0}
    if u_data.get("balance",0) < price: return await interaction.response.send_message(f"❌ Need Rs {price}. Balance: Rs {u_data.get('balance')}",ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    overwrites = {interaction.guild.default_role:discord.PermissionOverwrite(view_channel=False), interaction.guild.me:discord.PermissionOverwrite(view_channel=True, manage_channels=True)}
    for m in m_list: overwrites[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)
    if ctype=="text": new_c = await interaction.guild.create_text_channel(name=name, overwrites=overwrites, category=bot.get_channel(CATEGORY_ID))
    else: new_c = await interaction.guild.create_voice_channel(name=name, overwrites=overwrites, category=bot.get_channel(CATEGORY_ID))
    users_col.update_one({"_id":uid},{"$inc":{"balance":-price}})
    active_chans.insert_one({"_id":new_c.id,"expire_at":datetime.utcnow()+timedelta(hours=hours),"guild_id":interaction.guild.id})
    await interaction.followup.send(f"✅ Created {new_c.mention} (Price: Rs {price})")

@bot.tree.command(name="findteam")
async def find_team(interaction: discord.Interaction, role:str, level:str, message:str):
    if interaction.channel.id != FIND_TEAM_ID: return await interaction.response.send_message("❌ Wrong channel.",ephemeral=True)
    e = discord.Embed(title="🟢 Team Finder", color=0x2ecc71)
    e.add_field(name="User", value=interaction.user.mention).add_field(name="Role", value=role).add_field(name="Level", value=level)
    e.add_field(name="Message", value=message, inline=False)
    msg = await interaction.channel.send(embed=e)
    team_finder_col.insert_one({"_id":msg.id,"expire_at":datetime.utcnow()+timedelta(minutes=30),"guild_id":interaction.guild.id})
    await interaction.response.send_message("✅ Live!",ephemeral=True)

@bot.tree.command(name="giveaway")
async def giveaway(interaction: discord.Interaction, time_mins:int, prize:str):
    if not await is_admin(interaction): return
    g_id = str(random.randint(1000,9999))
    embed = discord.Embed(title="🎉 Giveaway Start!", description=f"Prize: **{prize}**\nEnds in: {time_mins} mins", color=0x00ff00)
    await interaction.response.send_message("Started!",ephemeral=True)
    msg = await interaction.channel.send(embed=embed, view=GiveawayView(g_id))
    giveaway_col.insert_one({"_id":g_id,"prize":prize,"participants":[],"msg_id":msg.id})
    await asyncio.sleep(time_mins*60)
    g = giveaway_col.find_one({"_id":g_id})
    winner = f"<@{random.choice(g['participants'])}>" if g['participants'] else "No one"
    await interaction.channel.send(f"🎊 Giveaway ended! Winner of **{prize}**: {winner}")
    giveaway_col.delete_one({"_id":g_id})

# --- KEEP ALIVE & RUN ---
keep_alive()
bot.run(TOKEN)
