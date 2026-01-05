import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
import aiohttp
from pymongo import MongoClient
import certifi

# --- DATABASE SETUP ---
MONGO_URI = os.getenv("MONGO_URI")
ca = certifi.where()
cluster = MongoClient(MONGO_URI, tlsCAFile=ca, tlsAllowInvalidCertificates=True)

db = cluster["tech4u_database"]
codes_col = db["codes"]
warns_col = db["warnings"]
vouch_col = db["vouch_permits"]

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

# --- VOUCH MONITOR (1 MSG LIMIT) ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id == VOUCH_CHANNEL_ID:
        uid = str(message.author.id)
        user_data = vouch_col.find_one({"_id": uid})
        if user_data and user_data.get("permits", 0) > 0:
            vouch_col.update_one({"_id": uid}, {"$inc": {"permits": -1}})
            await message.add_reaction("✅")
            if vouch_col.find_one({"_id": uid}).get("permits", 0) == 0:
                await message.channel.set_permissions(message.author, send_messages=False)
        else:
            try: await message.delete()
            except: pass

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

        # Create Channel with 10-minute lifetime permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=is_youtube, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        temp_chan = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
        await interaction.followup.send(f"✅ Success! Go to {temp_chan.mention}", ephemeral=True)

        if is_youtube:
            await temp_chan.send(f"{member.mention} ⚠️ **YouTube Premium Code Detected!**\nPlease **TYPE YOUR GMAIL** here so the admin can upgrade your account.")
            
            def check(m):
                return m.author == member and m.channel == temp_chan

            try:
                # Wait for user to type Gmail
                msg = await bot.wait_for('message', check=check, timeout=300.0) 
                user_gmail = msg.content
                
                # Send to your specific channel 1457609174350303324
                log_chan = bot.get_channel(GMAIL_LOG_CHANNEL_ID)
                if log_chan:
                    await log_chan.send(f"📬 **YT Premium Request**\nUser: {member.mention}\nGmail: `{user_gmail}`\nCode Used: `{code}`")
                
                await temp_chan.send("✅ **Gmail received!** Admin will invite you shortly.")
            except asyncio.TimeoutError:
                await temp_chan.send("⏰ Timeout! You didn't provide a Gmail address.")
        else:
            # Regular Service Info
            embed = discord.Embed(title="🎁 Account Details Delivered!", color=discord.Color.green())
            embed.add_field(name="Service", value=f"**{item['service']}**", inline=False)
            embed.add_field(name="Email/ID", value=f"`{item['email']}`", inline=True)
            embed.add_field(name="Password", value=f"`{item['password']}`", inline=True)
            await temp_chan.send(content=member.mention, embed=embed)

        # Give Vouch Permit & Template
        vouch_msg = f"`{code} I got {item['service']}, thanks @admin`"
        await temp_chan.send(f"📢 **VOUCH REQUIRED:** Copy & Paste this in <#{VOUCH_CHANNEL_ID}>:\n{vouch_msg}\n\n⏰ *This channel deletes in 10 minutes.*")
        
        await bot.get_channel(VOUCH_CHANNEL_ID).set_permissions(member, send_messages=True)
        vouch_col.update_one({"_id": str(member.id)}, {"$inc": {"permits": 1}}, upsert=True)

        # Webhook Log
        log = discord.Embed(title="📜 New Redemption", color=discord.Color.blue())
        log.add_field(name="User", value=f"{member.mention}", inline=True)
        log.add_field(name="Item", value=item['service'], inline=True)
        await send_webhook_log(embed=log)

        # Keep channel alive for 10 minutes
        await asyncio.sleep(600)
        await temp_chan.delete()

        # Vouch Check Punishment
        user_vouch = vouch_col.find_one({"_id": str(member.id)})
        if user_vouch and user_vouch.get("permits", 0) > 0:
            warns_col.update_one({"_id": str(member.id)}, {"$inc": {"count": 1}}, upsert=True)
            w_data = warns_col.find_one({"_id": str(member.id)})
            warn_chan = bot.get_channel(WARN_CHANNEL_ID)
            if warn_chan:
                await warn_chan.send(f"msg in vouches {member.mention}")
            
            if w_data['count'] >= 3:
                await member.ban(reason="3 Warnings for no vouching")

    except Exception as e:
        print(f"Error: {e}")

@bot.tree.command(name="help", description="How to use Tech4U")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U Help", color=discord.Color.blue())
    embed.description = "1️⃣ Get code from GP Link\n2️⃣ `/redeem code:[code]`\n3️⃣ Open private channel\n4️⃣ Vouch in #vouches"
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
