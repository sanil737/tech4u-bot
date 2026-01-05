import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
import aiohttp
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- KEEP ALIVE SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "Tech4U Bot is Online 24/7!"

def run():
    # Render dynamic port detection
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- DATABASE SETUP (MongoDB) ---
MONGO_URI = os.getenv("MONGO_URI")
cluster = MongoClient(MONGO_URI)
db = cluster["tech4u_database"]
codes_col = db["codes"]
warns_col = db["warnings"]
vouch_col = db["vouch_permits"]

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = "https://discord.com/api/webhooks/1457635950942490645/fD3vFDv7IExZcZqEp6rLNd0cy1RM_Ccjv53o4Ne64HUhV5WRAmyKWpc7ph9J7lIMthD8"
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626

async def send_webhook_log(embed=None):
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
        await webhook.send(embed=embed, username="Tech4U Logs")

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
    print(f'Logged in as {bot.user}')

# --- VOUCH MONITOR (1 MSG LIMIT) ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        user_vouch = vouch_col.find_one({"_id": uid})
        
        if user_data := user_vouch:
            if user_data.get("permits", 0) > 0:
                vouch_col.update_one({"_id": uid}, {"$inc": {"permits": -1}})
                await message.add_reaction("✅")
                
                # Check if now 0
                updated = vouch_col.find_one({"_id": uid})
                if updated.get("permits", 0) == 0:
                    await message.channel.set_permissions(message.author, send_messages=False)
                return
        
        # If no permit, delete message
        await message.delete()
        await message.channel.send(f"❌ {message.author.mention}, redeem a code first!", delete_after=5)

# --- ADMIN: ANNOUNCE ---
@bot.tree.command(name="announce", description="Send a professional announcement")
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    embed = discord.Embed(title=title, description=message.replace("\\n", "\n"), color=discord.Color.gold())
    embed.set_footer(text=f"Sent by {interaction.user.display_name}")
    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Announcement sent!", ephemeral=True)

# --- ADMIN: ADD CODE ---
@bot.tree.command(name="addcode", description="Add account details (Saved Forever)")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    codes_col.update_one(
        {"_id": code}, 
        {"$set": {"service": service, "email": email, "password": password}}, 
        upsert=True
    )
    await interaction.response.send_message(f"✅ Code `{code}` added for **{service}**.", ephemeral=True)

# --- USER: REDEEM ---
@bot.tree.command(name="redeem", description="Redeem code in a private 10-minute channel")
async def redeem(interaction: discord.Interaction, code: str):
    # Strictly one-time: find and delete from DB
    item = codes_col.find_one_and_delete({"_id": code})
    
    if not item:
        return await interaction.response.send_message("❌ Invalid or used code!", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        member = interaction.user
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        
        temp_chan = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
        
        embed = discord.Embed(title="🎁 Account Details Delivered!", color=discord.Color.green())
        embed.add_field(name="Service", value=f"**{item['service']}**", inline=False)
        embed.add_field(name="Email/ID", value=f"`{item['email']}`", inline=True)
        embed.add_field(name="Password", value=f"`{item['password']}`", inline=True)
        embed.description = f"📢 **VOUCH REQUIRED:** Go to <#{VOUCH_CHANNEL_ID}> and vouch!\n*Failure to vouch = Warning!*"
        
        await temp_chan.send(content=member.mention, embed=embed)

        # Unlock Vouch Channel
        vouch_chan = bot.get_channel(VOUCH_CHANNEL_ID)
        await vouch_chan.set_permissions(member, send_messages=True)
        vouch_col.update_one({"_id": str(member.id)}, {"$inc": {"permits": 1}}, upsert=True)

        # Log to Webhook
        log = discord.Embed(title="📜 New Redemption", color=discord.Color.blue())
        log.add_field(name="User", value=f"{member.mention}", inline=True)
        log.add_field(name="Item", value=item['service'], inline=True)
        await send_webhook_log(embed=log)

        await interaction.followup.send(f"✅ Success! Go to {temp_chan.mention}", ephemeral=True)

        # 10 minute timer
        await asyncio.sleep(600)
        await temp_chan.delete()

        # Check for punishment
        p_check = vouch_col.find_one({"_id": str(member.id)})
        if p_check and p_check.get("permits", 0) > 0:
            warns_col.update_one({"_id": str(member.id)}, {"$inc": {"count": 1}}, upsert=True)
            w_data = warns_col.find_one({"_id": str(member.id)})
            
            warn_chan = bot.get_channel(WARN_CHANNEL_ID)
            await warn_chan.send(f"msg in vouches {member.mention}")
            
            if w_data['count'] >= 3:
                await member.ban(reason="3 Warnings for not vouching.")
                await warn_chan.send(f"🚫 **{member}** has been banned for 3 days.")

    except Exception as e:
        print(f"Error: {e}")
        await interaction.followup.send("❌ Bot error. Check Admin permissions.", ephemeral=True)

# --- HELP ---
@bot.tree.command(name="help", description="Learn how to use Tech4U")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U Help Center", color=discord.Color.blue())
    embed.add_field(name="1️⃣ Get Code", value="Get code from your GP Link.", inline=False)
    embed.add_field(name="2️⃣ Redeem", value="Type `/redeem code:[your_code]`.", inline=False)
    embed.add_field(name="3️⃣ Private Channel", value="Go to the 10-minute channel the bot creates.", inline=False)
    embed.add_field(name="⚠️ Vouch", value="Vouch in <#1457654896449818686> or get a warning!", inline=False)
    await interaction.response.send_message(embed=embed)

keep_alive()
bot.run(TOKEN)
