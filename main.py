import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
import aiohttp
from flask import Flask
from threading import Thread

# --- KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run)
    t.start()

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
DATA_FILE = "codes.json"
VOUCH_FILE = "vouch_permits.json"
WARN_FILE = "warnings.json"

# YOUR WEBHOOK URL
WEBHOOK_URL = "https://discord.com/api/webhooks/1457635950942490645/fD3vFDv7IExZcZqEp6rLNd0cy1RM_Ccjv53o4Ne64HUhV5WRAmyKWpc7ph9J7lIMthD8"

# YOUR CHANNEL IDs
VOUCH_CHANNEL_ID = 1457654896449818686 
WARN_CHANNEL_ID = 1457658131499843626

def load_data(file):
    if not os.path.exists(file): return {}
    try:
        with open(file, "r") as f: return json.load(f)
    except: return {}

def save_data(data, file):
    with open(DATA_FILE if file == "codes" else file, "w") as f: json.dump(data, f, indent=4)

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

# --- VOUCH MONITOR: ALLOWS ONLY 1 MSG PER CODE ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id == VOUCH_CHANNEL_ID:
        permits = load_data(VOUCH_FILE)
        uid = str(message.author.id)
        
        if uid in permits and permits[uid] > 0:
            permits[uid] -= 1
            save_data(permits, VOUCH_FILE)
            await message.add_reaction("✅")
            
            # Lock the channel for the user after their vouch
            if permits[uid] == 0:
                await message.channel.set_permissions(message.author, send_messages=False)
        else:
            # Delete random messages or spam
            await message.delete()
            await message.channel.send(f"❌ {message.author.mention}, you must redeem a code to vouch here!", delete_after=5)

# --- ADMIN: ADD CODE ---
@bot.tree.command(name="addcode", description="Add account details (Admin Only)")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    data = load_data("codes")
    data[code] = {"service": service, "email": email, "password": password}
    save_data(data, "codes")
    await interaction.response.send_message(f"✅ Code `{code}` registered for **{service}**.", ephemeral=True)

# --- USER: REDEEM ---
@bot.tree.command(name="redeem", description="Redeem code in a private 10-minute channel")
async def redeem(interaction: discord.Interaction, code: str):
    data = load_data("codes")
    if code not in data:
        return await interaction.response.send_message("❌ Invalid or used code!", ephemeral=True)

    item = data.pop(code)
    save_data(data, "codes")
    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        member = interaction.user

        # Create Private Channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        temp_chan = await guild.create_text_channel(name=f"🎁-redeem-{member.name}", overwrites=overwrites)
        
        embed = discord.Embed(title="🎁 Account Details Delivered!", color=discord.Color.green())
        embed.add_field(name="Service", value=f"**{item['service']}**", inline=False)
        embed.add_field(name="Email/ID", value=f"`{item['email']}`", inline=True)
        embed.add_field(name="Password", value=f"`{item['password']}`", inline=True)
        embed.description = f"📢 **VOUCH REQUIRED:** Go to <#{VOUCH_CHANNEL_ID}> and vouch for us!\n*Failure to vouch = Warning!*"
        await temp_chan.send(content=member.mention, embed=embed)

        # Unlock Vouch Channel
        vouch_chan = bot.get_channel(VOUCH_CHANNEL_ID)
        await vouch_chan.set_permissions(member, send_messages=True)

        # Add Vouch Permit
        permits = load_data(VOUCH_FILE)
        permits[str(member.id)] = permits.get(str(member.id), 0) + 1
        save_data(permits, VOUCH_FILE)

        # Log to Webhook
        log = discord.Embed(title="📜 New Redemption", color=discord.Color.blue())
        log.add_field(name="User", value=f"{member.mention}", inline=True)
        log.add_field(name="Item", value=item['service'], inline=True)
        await send_webhook_log(embed=log)

        await interaction.followup.send(f"✅ Success! Check your private channel: {temp_chan.mention}", ephemeral=True)

        # Wait 10 mins
        await asyncio.sleep(600)
        await temp_chan.delete()

        # Punishment Check
        permits = load_data(VOUCH_FILE)
        if permits.get(str(member.id), 0) > 0:
            warns = load_data(WARN_FILE)
            warns[str(member.id)] = warns.get(str(member.id), 0) + 1
            save_data(warns, WARN_FILE)
            
            warn_chan = bot.get_channel(WARN_CHANNEL_ID)
            count = warns[str(member.id)]
            await warn_chan.send(f"⚠️ {member.mention}, you didn't vouch! Warning **#{count}/3**.")
            
            if count >= 3:
                await member.ban(reason="3 Warnings for not vouching.")
                await warn_chan.send(f"🚫 **{member}** has been banned for 3 days.")

    except Exception as e:
        print(e)
        await interaction.followup.send("❌ Error. Ensure bot has Administrator permissions.", ephemeral=True)

# --- HELP ---
@bot.tree.command(name="help", description="Learn how to use Tech4U")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U System", color=discord.Color.blue())
    embed.description = "1️⃣ Get code from GP Link\n2️⃣ Use `/redeem` here\n3️⃣ Open private channel\n4️⃣ Vouch in <#1457654896449818686>"
    await interaction.response.send_message(embed=embed)

keep_alive()
bot.run(TOKEN)
