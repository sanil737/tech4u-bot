import discord
from discord import app_commands
from discord.ext import commands, tasks
import os, asyncio, random, certifi
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

# -------------------- KEEP ALIVE --------------------
app = Flask("")
@app.route("/")
def home():
    return "enjoined_gaming Bot Online"

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

Thread(target=run).start()

# -------------------- DATABASE --------------------
MONGO_URI = os.getenv("MONGO_URI")
cluster = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = cluster["enjoined_gaming"]

users = db["users"]
temp_channels = db["temp_channels"]
team_posts = db["team_posts"]
giveaways = db["giveaways"]
settings = db["settings"]
tickets = db["tickets"]

# -------------------- CONFIG --------------------
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [1458812527055212585,986251574982606888]

PRIVATE_CATEGORY_ID = 1459557142850830489
FIND_TEAM_CHANNEL = 1459469475849175304
WARN_CHANNEL = 1459448651704303667

EG_COND = "📜 **EG Cond**: Respect all | No abuse | Follow rules"

PRICES = {
    "text": {2:{1:400,2:700,4:1200},3:{1:500,2:900,4:1500},4:{1:600,2:1100,4:1800}},
    "voice":{2:{1:500,2:900,4:1500},3:{1:650,2:1100,4:1800},4:{1:800,2:1400,4:2300}}
}

# -------------------- BOT --------------------
class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=".", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        self.cleanup.start()

bot = Bot()

# -------------------- HELPERS --------------------
def is_admin(user):
    return user.id in ADMIN_IDS or user.guild_permissions.administrator

def price_calc(type_, users_count, hours):
    users_count = min(max(users_count, 2), 4)
    hours = 1 if hours not in [1,2,4] else hours
    return PRICES[type_][users_count][hours]

# -------------------- CLEANUP --------------------
@tasks.loop(minutes=1)
async def cleanup():
    now = datetime.utcnow()

    for ch in temp_channels.find({"expire": {"$lte": now}}):
        guild = bot.get_guild(ch["guild"])
        if guild:
            channel = guild.get_channel(ch["_id"])
            if channel:
                await channel.delete()

        users.update_many({"in_room": ch["_id"]}, {"$set": {"in_room": None}})
        temp_channels.delete_one({"_id": ch["_id"]})

# -------------------- DAILY --------------------
@bot.tree.command(name="daily")
async def daily(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    data = users.find_one({"_id": uid}) or {"bal":0,"last":datetime.min}

    if datetime.utcnow() - data["last"] < timedelta(hours=24):
        return await interaction.response.send_message("⏳ Come back in 24h", ephemeral=True)

    users.update_one(
        {"_id": uid},
        {"$set":{"last":datetime.utcnow()}, "$inc":{"bal":100}},
        upsert=True
    )
    await interaction.response.send_message("🎁 You got **100 credits**!")

# -------------------- FIND TEAM --------------------
@bot.tree.command(name="findteam")
async def findteam(interaction: discord.Interaction, role:str, level:str, message:str):
    if interaction.channel.id != FIND_TEAM_CHANNEL:
        return await interaction.response.send_message("❌ Use this in find-team channel", ephemeral=True)

    embed = discord.Embed(title="🎮 Team Finder", color=0x2ecc71)
    embed.add_field(name="User", value=interaction.user.mention)
    embed.add_field(name="Role", value=role)
    embed.add_field(name="Level", value=level)
    embed.add_field(name="Message", value=message, inline=False)

    msg = await interaction.channel.send(embed=embed)
    team_posts.insert_one({
        "_id": msg.id,
        "guild": interaction.guild.id,
        "expire": datetime.utcnow() + timedelta(minutes=30)
    })

    await interaction.response.send_message("✅ Posted", ephemeral=True)

# -------------------- PRIVATE CHANNEL --------------------
@bot.tree.command(name="makeprivatechannel")
async def makeprivate(
    interaction: discord.Interaction,
    type_: str,
    name: str,
    hours: int,
    user2: discord.Member,
    user3: discord.Member = None,
    user4: discord.Member = None
):
    uid = str(interaction.user.id)

    if users.find_one({"_id": uid, "in_room": {"$ne": None}}):
        return await interaction.response.send_message(
            "❌ You are already in a private room.", ephemeral=True)

    members = [interaction.user, user2, user3, user4]
    members = [m for m in members if m]

    if len(members) < 2:
        return await interaction.response.send_message("❌ Minimum 2 users required", ephemeral=True)

    price = price_calc(type_, len(members), hours)
    bal = users.find_one({"_id": uid}) or {"bal":0}

    if bal["bal"] < price:
        return await interaction.response.send_message(
            f"❌ Need Rs {price}. Balance Rs {bal['bal']}", ephemeral=True)

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)
    }

    for m in members:
        overwrites[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)

    category = interaction.guild.get_channel(PRIVATE_CATEGORY_ID)

    if type_ == "text":
        channel = await interaction.guild.create_text_channel(name=name, overwrites=overwrites, category=category)
    else:
        channel = await interaction.guild.create_voice_channel(name=name, overwrites=overwrites, category=category)

    users.update_one({"_id": uid}, {"$inc":{"bal":-price}}, upsert=True)

    for m in members:
        users.update_one({"_id": str(m.id)}, {"$set":{"in_room": channel.id}}, upsert=True)

    temp_channels.insert_one({
        "_id": channel.id,
        "guild": interaction.guild.id,
        "expire": datetime.utcnow() + timedelta(hours=hours)
    })

    await channel.send(f"⏰ Auto delete in **{hours} hour(s)**\n{EG_COND}")
    await interaction.response.send_message(f"✅ Created {channel.mention}", ephemeral=True)

# -------------------- LOCK / UNLOCK --------------------
@bot.tree.command(name="lock")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user): return
    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        send_messages=False,
        send_messages_in_threads=False,
        create_public_threads=False,
        create_private_threads=False
    )
    await interaction.response.send_message("🔒 Locked")

@bot.tree.command(name="unlock")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Unlocked")

# -------------------- TICKETS --------------------
class TicketView(discord.ui.View):
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green)
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        if tickets.find_one({"user": interaction.user.id}):
            return await interaction.response.send_message("❌ Ticket already open", ephemeral=True)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True)
        }

        ch = await interaction.guild.create_text_channel(
            f"ticket-{interaction.user.name}", overwrites=overwrites)

        tickets.insert_one({"user": interaction.user.id, "channel": ch.id})
        await ch.send(f"Welcome {interaction.user.mention}, support will assist you.")
        await interaction.response.send_message("✅ Ticket created", ephemeral=True)

@bot.tree.command(name="ticket_setup")
async def ticket_setup(interaction: discord.Interaction):
    if not is_admin(interaction.user): return
    await interaction.channel.send("Need help? Click below", view=TicketView())
    await interaction.response.send_message("✅ Done", ephemeral=True)

# -------------------- RUN --------------------
bot.run(TOKEN)
