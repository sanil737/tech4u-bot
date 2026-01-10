import discord
from discord import app_commands
from discord.ext import commands, tasks
import os, asyncio, random, certifi, aiohttp
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# --- 1. KEEP ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): return "enjoined_gaming God Bot Online 24/7!"
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

# --- 3. CONFIGURATION (IDs) ---
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [986251574982606888, 1458812527055212585]
EG_COND = "📜 **EG Cond**: Respect all | Vouch after use | Follow rules"
WELCOME_ID = 1459444229255200971
FIND_TEAM_ID = 1459469475849175304
VOUCH_ID = 1459448284530610288
REDEEM_LOG_ID = 1459556690536960100
WARN_ID = 1459448651704303667
GMAIL_LOG_ID = 1457609174350303324
CATEGORY_ID = 1459557142850830489

# --- PRICING LOGIC ---
PRICES = {
    "text": {2: {1:400,2:700,4:1200},3:{1:500,2:900,4:1500},4:{1:600,2:1100,4:1800},5:{1:750,2:1300,4:2100},6:{1:900,2:1500,4:2500},7:{1:1050,2:1700,4:2800}},
    "voice": {2:{1:500,2:900,4:1500},3:{1:650,2:1100,4:1800},4:{1:800,2:1400,4:2300},5:{1:1000,2:1800,4:2900},6:{1:1200,2:2100,4:3400},7:{1:1400,2:2400,4:3900}}
}

def get_room_price(ctype, users, hours):
    users = max(2, min(users, 7))
    hours = hours if hours in [1,2,4] else 1
    return PRICES[ctype][users][hours]

async def is_admin(interaction):
    return interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.administrator

# --- UI COMPONENTS ---
class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary, custom_id="ot")
    async def ot(self, interaction: discord.Interaction, button: discord.ui.Button):
        if ticket_col.find_one({"owner": interaction.user.id, "status":"open"}):
            return await interaction.response.send_message("❌ Ticket already open!", ephemeral=True)
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
        chan = await interaction.guild.create_text_channel(name=f"ticket-{interaction.user.name}", overwrites=overwrites)
        ticket_col.insert_one({"_id": chan.id, "owner": interaction.user.id, "status":"open"})
        await chan.send(f"Welcome {interaction.user.mention}! Use `/close` to end.")
        await interaction.response.send_message(f"✅ Ticket: {chan.mention}", ephemeral=True)

class GiveawayView(discord.ui.View):
    def __init__(self, g_id):
        super().__init__(timeout=None)
        self.g_id = g_id
    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.success, custom_id="jg")
    async def jg(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_col.update_one({"_id": self.g_id}, {"$addToSet":{"participants":interaction.user.id}})
        await interaction.response.send_message("✅ Joined!", ephemeral=True)

# --- BOT CLASS ---
class EG_Bot(commands.Bot):
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
            users_col.update_many({"in_room":chan["_id"]}, {"$set":{"in_room":None}})
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

bot = EG_Bot()

# --- EVENTS ---
@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_ID)
    if ch: await ch.send(f"🎮 Welcome to **enjoined_gaming**, {member.mention}! 🎉\nDon’t forget to pick a role. Use `/help` to start! 😎")

@bot.event
async def on_message(message):
    if message.author.bot: return
    # Daily logic
    if message.content.lower() == ".daily":
        uid = str(message.author.id)
        now = datetime.utcnow()
        data = users_col.find_one({"_id":uid}) or {"balance":0,"last":datetime.min,"streak":0}
        if now - data.get("last",datetime.min) > timedelta(days=1):
            streak = data.get("streak",0)+1 if now - data.get("last",datetime.min) < timedelta(days=2) else 1
            reward = 100 + (streak*10) if streak<7 else 300
            users_col.update_one({"_id":uid},{"$inc":{"balance":reward},"$set":{"last":now,"streak":streak}},upsert=True)
            await message.channel.send(f"✅ Received **{reward} credits**! (Streak: {streak} days)")
        else: await message.channel.send("⏳ Claim in 24h")

    # Vouch
    if message.channel.id == VOUCH_ID:
        uid = str(message.author.id)
        if vouch_col.find_one_and_delete({"_id": uid}):
            await message.add_reaction("✅")
            await message.channel.send(f"✅ Vouch verified! Thanks {message.author.mention}", delete_after=10)
            await message.channel.set_permissions(message.author, send_messages=False)
        elif not await is_admin(message): await message.delete()

# --- TIMER LOGIC ---
async def start_vouch_logic(member, temp_chan):
    warn_ch = bot.get_channel(WARN_ID)
    for i in range(1,4):
        await asyncio.sleep(600)
        if vouch_col.find_one({"_id":str(member.id)}):
            if i==1: await warn_ch.send(f"⚠️ Reminder {member.mention} vouch in <#{VOUCH_ID}>.")
            if i==2: await warn_ch.send(f"⚠️ Second Warning {member.mention} vouch now!")
            if i==3 and member.id not in ADMIN_IDS:
                unban_at = datetime.utcnow()+timedelta(days=3)
                bans_col.update_one({"_id":member.id},{"$set":{"unban_at":unban_at,"guild_id":member.guild.id}},upsert=True)
                await member.ban(reason="No Vouch")
    try: await temp_chan.delete()
    except: pass

# --- SLASH COMMANDS ---
@bot.tree.command(name="redeem")
async def redeem(interaction: discord.Interaction, code: str):
    if (settings_col.find_one({"_id":"panic"}) or {"v":False})["v"]: return await interaction.response.send_message("🚨 Panic Mode active.")
    uid = str(interaction.user.id)
    u_data = users_col.find_one({"_id": uid})
    if u_data and (datetime.utcnow() - u_data.get("last_red", datetime.min)) < timedelta(days=1):
        return await interaction.response.send_message("❌ Wait 24h.", ephemeral=True)
    
    item = codes_col.find_one_and_delete({"_id": code})
    if not item: return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    users_col.update_one({"_id": uid}, {"$set": {"last_red": datetime.utcnow()}}, upsert=True)
    await bot.get_channel(REDEEM_LOG_ID).send(f"Code **[{code}]** used by {interaction.user.mention}")
    
    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)}
    temp = await interaction.guild.create_text_channel(name=f"🎁-{interaction.user.name}", overwrites=overwrites, category=bot.get_channel(CATEGORY_ID))
    
    if "youtube" in item['service'].lower():
        await temp.send(f"{interaction.user.mention} Type your Gmail:")
        try:
            msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == temp, timeout=300)
            await bot.get_channel(GMAIL_LOG_ID).send(f"📬 **YT Request**: {interaction.user.mention} | Gmail: `{msg.content}`")
        except: pass
    else:
        e = discord.Embed(title="🎁 Account Info", color=0x2ecc71); e.add_field(name="Svc", value=item['service']).add_field(name="ID", value=item['email']).add_field(name="Pass", value=item['password'])
        e.description = "⏰ Channel deletes in 30 mins."
        await temp.send(embed=e)
    
    vouch_col.update_one({"_id": uid}, {"$set": {"active": True}}, upsert=True)
    await bot.get_channel(VOUCH_ID).set_permissions(interaction.user, send_messages=True)
    await interaction.followup.send(f"✅ Go to {temp.mention}"); asyncio.create_task(start_vouch_logic(interaction.user, temp))

@bot.tree.command(name="makeprivatechannel")
async def make_p(interaction: discord.Interaction, ctype:str, name:str, hours:int, u2:discord.Member, u3:discord.Member=None, u4:discord.Member=None, u5:discord.Member=None, u6:discord.Member=None, u7:discord.Member=None):
    if (settings_col.find_one({"_id":"panic"}) or {"v":False})["v"]: return await interaction.response.send_message("🚨 Panic Mode active.")
    uid = str(interaction.user.id)
    m_list = [m for m in [interaction.user,u2,u3,u4,u5,u6,u7] if m]
    price = get_room_price(ctype.lower(), len(m_list), hours)
    u_data = users_col.find_one({"_id":uid}) or {"balance":0}
    if u_data.get("balance") < price: return await interaction.response.send_message(f"❌ Need Rs {price}.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)}
    for m in m_list: overwrites[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)
    if ctype.lower()=="text": new_c = await interaction.guild.create_text_channel(name=name, overwrites=overwrites, category=bot.get_channel(CATEGORY_ID))
    else: new_c = await interaction.guild.create_voice_channel(name=name, overwrites=overwrites, category=bot.get_channel(CATEGORY_ID))
    
    users_col.update_one({"_id":uid},{"$inc":{"balance":-price}}); active_chans.insert_one({"_id":new_c.id,"expire_at":datetime.utcnow()+timedelta(hours=hours),"guild_id":interaction.guild.id})
    await interaction.followup.send(f"✅ Created {new_c.mention}")

@bot.tree.command(name="daily")
async def d_slash(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    data = users_col.find_one({"_id":uid}) or {"balance":0,"last":datetime.min}
    if datetime.utcnow() - data.get("last",datetime.min) > timedelta(days=1):
        users_col.update_one({"_id":uid},{"$inc":{"balance":100},"$set":{"last":datetime.utcnow()}},upsert=True)
        await interaction.response.send_message("✅ Claimed 100 credits!")
    else: await interaction.response.send_message("⏳ Try again in 24h", ephemeral=True)

@bot.tree.command(name="lock")
async def lock(interaction: discord.Interaction):
    if not await is_admin(interaction): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    await interaction.response.send_message("🔒 Locked.")

@bot.tree.command(name="unlock")
async def unlock(interaction: discord.Interaction):
    if not await is_admin(interaction): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Unlocked.")

@bot.tree.command(name="clear")
async def clear(interaction: discord.Interaction, amount:int):
    if not await is_admin(interaction): return
    await interaction.channel.purge(limit=amount); await interaction.response.send_message(f"🧹 Deleted {amount}", ephemeral=True)

@bot.tree.command(name="addcode")
async def add(interaction: discord.Interaction, code:str, service:str, email:str, password:str):
    if not await is_admin(interaction): return
    codes_col.update_one({"_id":code}, {"$set":{"service":service,"email":email,"password":password}}, upsert=True)
    await interaction.response.send_message(f"✅ Added {code}")

@bot.tree.command(name="addcoins")
async def coins(interaction: discord.Interaction, user:discord.Member, amount:int):
    if not await is_admin(interaction): return
    users_col.update_one({"_id":str(user.id)}, {"$inc":{"balance":amount}}, upsert=True)
    await interaction.response.send_message(f"✅ Added {amount} coins to {user.mention}")

@bot.tree.command(name="status")
async def status(interaction: discord.Interaction):
    d = users_col.find_one({"_id":str(interaction.user.id)}) or {"balance":0}
    await interaction.response.send_message(f"💰 Balance: Rs {d.get('balance')}\n🛡️ {EG_COND}", ephemeral=True)

@bot.tree.command(name="ticket_setup")
async def t_setup(interaction: discord.Interaction):
    if not await is_admin(interaction): return
    await interaction.channel.send("📩 Need help? Click below!", view=TicketView())
    await interaction.response.send_message("Done.", ephemeral=True)

@bot.tree.command(name="giveaway")
async def gway(interaction: discord.Interaction, time_mins:int, prize:str):
    if not await is_admin(interaction): return
    g_id = str(random.randint(1000,9999))
    e = discord.Embed(title="🎉 Giveaway!", description=f"Prize: **{prize}**", color=0x00ff00)
    msg = await interaction.channel.send(embed=e, view=GiveawayView(g_id))
    giveaway_col.insert_one({"_id":g_id,"prize":prize,"participants":[],"msg_id":msg.id})
    await interaction.response.send_message("Started!", ephemeral=True)
    await asyncio.sleep(time_mins*60); g = giveaway_col.find_one({"_id":g_id})
    w = f"<@{random.choice(g['participants'])}>" if g['participants'] else "No one"; await interaction.channel.send(f"Winner of **{prize}**: {w}")

@bot.tree.command(name="findteam")
async def fteam(interaction: discord.Interaction, role:str, level:str, message:str):
    if interaction.channel.id != FIND_TEAM_ID: return await interaction.response.send_message("❌ Wrong channel.", ephemeral=True)
    e = discord.Embed(title="🟢 Team Finder", color=0x2ecc71)
    e.add_field(name="User", value=interaction.user.mention).add_field(name="Role", value=role).add_field(name="Level", value=level).add_field(name="Message", value=message, inline=False)
    msg = await interaction.channel.send(embed=e)
    team_finder_col.insert_one({"_id":msg.id,"expire_at":datetime.utcnow()+timedelta(minutes=30),"guild_id":interaction.guild.id})
    await interaction.response.send_message("✅ Posted.", ephemeral=True)

# --- START ---
keep_alive()
bot.run(TOKEN)
