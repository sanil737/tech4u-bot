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

# --- KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Tech4U Bot is Online 24/7!"
def run():
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

# --- VOUCH MONITOR (STRICT 1 MSG RULE) ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        user_data = vouch_col.find_one({"_id": uid})
        
        if user_data and user_data.get("permits", 0) > 0:
            # Consume 1 vouch permit
            vouch_col.update_one({"_id": uid}, {"$inc": {"permits": -1}})
            await message.add_reaction("✅")
            
            # Re-check: if no more permits left, lock the channel for them
            updated_data = vouch_col.find_one({"_id": uid})
            if updated_data.get("permits", 0) == 0:
                await message.channel.set_permissions(message.author, send_messages=False)
        else:
            # No permit? Delete message immediately
            await message.delete()
            await message.channel.send(f"❌ {message.author.mention}, you can only vouch after a successful redeem!", delete_after=5)

# --- ADMIN: ANNOUNCE ---
@bot.tree.command(name="announce", description="Send a professional announcement")
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    embed = discord.Embed(title=title, description=message.replace("\\n", "\n"), color=discord.Color.gold())
    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Sent!", ephemeral=True)

# --- ADMIN: ADD CODE ---
@bot.tree.command(name="addcode", description="Add account details to database")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    codes_col.update_one({"_id": code}, {"$set": {"service": service, "email": email, "password": password}}, upsert=True)
    await interaction.response.send_message(f"✅ Code `{code}` registered.", ephemeral=True)

# --- USER: REDEEM ---
@bot.tree.command(name="redeem", description="Redeem code in a private 10-minute channel")
async def redeem(interaction: discord.Interaction, code: str):
    # Find and delete code (one-time use)
    item = codes_col.find_one_and_delete({"_id": code})
    
    if not item:
        return await interaction.response.send_message("❌ Invalid or already used code!", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        member = interaction.user
        
        # Create private permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        temp_chan = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
        
        # Display Info & Vouch Template
        embed = discord.Embed(title="🎁 Account Details Delivered!", color=discord.Color.green())
        embed.add_field(name="Service", value=f"**{item['service']}**", inline=False)
        embed.add_field(name="Email/ID", value=f"`{item['email']}`", inline=True)
        embed.add_field(name="Password", value=f"`{item['password']}`", inline=True)
        
        vouch_template = f"`{code} I got {item['service']}, thanks @admin`"
        embed.add_field(name="📋 Vouch Template (Copy & Paste)", value=vouch_template, inline=False)
        embed.description = f"📢 **VOUCH REQUIRED:** Copy the template above and paste it in <#{VOUCH_CHANNEL_ID}>!\n*Failure to vouch in 10 mins = Warning.*"
        
        await temp_chan.send(content=member.mention, embed=embed)

        # Unlock Vouch Channel for User & Add Permit
        vouch_chan = bot.get_channel(VOUCH_CHANNEL_ID)
        await vouch_chan.set_permissions(member, send_messages=True)
        vouch_col.update_one({"_id": str(member.id)}, {"$inc": {"permits": 1}}, upsert=True)

        # Log to Webhook
        log = discord.Embed(title="📜 New Redemption", color=discord.Color.blue())
        log.add_field(name="User", value=f"{member.mention}", inline=True)
        log.add_field(name="Service", value=item['service'], inline=True)
        log.add_field(name="Code", value=f"`{code}`", inline=False)
        await send_webhook_log(embed=log)

        await interaction.followup.send(f"✅ Success! Please check your private channel: {temp_chan.mention}", ephemeral=True)

        # 10 minute check
        await asyncio.sleep(600)
        await temp_chan.delete()

        # Check if they used their vouch permit
        user_vouch = vouch_col.find_one({"_id": str(member.id)})
        if user_vouch and user_vouch.get("permits", 0) > 0:
            # User failed to vouch
            warns_col.update_one({"_id": str(member.id)}, {"$inc": {"count": 1}}, upsert=True)
            w_data = warns_col.find_one({"_id": str(member.id)})
            
            warn_chan = bot.get_channel(WARN_CHANNEL_ID)
            await warn_chan.send(f"msg in vouches {member.mention}")
            
            if w_data['count'] >= 3:
                await member.ban(reason="3 Warnings for not vouching.")
                await warn_chan.send(f"🚫 **{member}** has been banned for 3 days (3 strikes).")

    except Exception as e:
        print(e)
        await interaction.followup.send("❌ Error. Ensure bot has 'Manage Channels' permission.", ephemeral=True)

# --- HELP ---
@bot.tree.command(name="help", description="Learn how to use Tech4U")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U Help Center", color=discord.Color.blue())
    embed.description = "1️⃣ Get code from GP Link\n2️⃣ Use `/redeem` here\n3️⃣ Open private channel\n4️⃣ Copy vouch template and paste in <#1457654896449818686>"
    await interaction.response.send_message(embed=embed)

keep_alive()
bot.run(TOKEN)
