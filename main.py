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

# --- CONFIG ---
TOKEN = os.getenv("TOKEN")
DATA_FILE = "codes.json"

# YOUR WEBHOOK URL
WEBHOOK_URL = "https://discord.com/api/webhooks/1457635950942490645/fD3vFDv7IExZcZqEp6rLNd0cy1RM_Ccjv53o4Ne64HUhV5WRAmyKWpc7ph9J7lIMthD8"

def load_data():
    if not os.path.exists(DATA_FILE): return {}
    try:
        with open(DATA_FILE, "r") as f: return json.load(f)
    except: return {}

def save_data(data):
    with open(DATA_FILE, "w") as f: json.dump(data, f, indent=4)

async def send_webhook_log(content=None, embed=None):
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
        await webhook.send(content=content, embed=embed, username="Tech4U Logs")

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/help | Tech4U"))
    print(f'Logged in as {bot.user}')

# --- HELP COMMAND (Detailed Version) ---
@bot.tree.command(name="help", description="Learn how to use the Tech4U Redeem System")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U Help Center", color=discord.Color.blue())
    embed.description = "Follow these steps to get your account:"
    embed.add_field(name="1️⃣ Find a Code", value="Complete the GP Link provided by the admin to get your secret code.", inline=False)
    embed.add_field(name="2️⃣ Redeem the Code", value="Type `/redeem code:[your_code]` in this server.", inline=False)
    embed.add_field(name="3️⃣ Private Channel", value="The bot will create a **private channel** for you. Look at the channel list to find it!", inline=False)
    embed.add_field(name="⚠️ Note", value="The private channel will delete itself after **10 minutes**. Please save your info fast!", inline=False)
    embed.set_footer(text="Tech4U - Fast, Secure, & Automatic")
    await interaction.response.send_message(embed=embed)

# --- ADMIN COMMAND: ANNOUNCE ---
@bot.tree.command(name="announce", description="Send a professional announcement (Admin Only)")
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    embed = discord.Embed(title=title, description=message.replace("\\n", "\n"), color=discord.Color.gold())
    embed.set_footer(text=f"Official Announcement from {interaction.user.display_name}")
    if bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)

    try:
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Announcement sent to {channel.mention}!", ephemeral=True)
    except:
        await interaction.response.send_message("❌ Error sending message. Check permissions.", ephemeral=True)

# --- ADMIN: ADD CODE ---
@bot.tree.command(name="addcode", description="Add account details to a code (Admin Only)")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    data = load_data()
    data[code] = {"service": service, "email": email, "password": password}
    save_data(data)
    await interaction.response.send_message(f"✅ Code `{code}` registered for **{service}**.", ephemeral=True)

# --- USER: REDEEM ---
@bot.tree.command(name="redeem", description="Redeem code in a private 10-minute channel")
async def redeem(interaction: discord.Interaction, code: str):
    data = load_data()
    
    if code not in data:
        return await interaction.response.send_message("❌ Invalid or already used code!", ephemeral=True)

    item = data.pop(code)
    save_data(data)
    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        member = interaction.user
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
        embed.description = "⏰ **This channel will delete itself in 10 minutes.**"
        embed.set_footer(text="Thank you for using Tech4U!")
        
        await temp_chan.send(content=member.mention, embed=embed)

        # WEBHOOK LOG
        log = discord.Embed(title="📜 New Redemption", color=discord.Color.blue())
        log.add_field(name="User", value=f"{member.mention} ({member.id})", inline=True)
        log.add_field(name="Item", value=item['service'], inline=True)
        log.add_field(name="Code", value=f"`{code}`", inline=False)
        await send_webhook_log(embed=log)

        await interaction.followup.send(f"✅ Success! Please check your private channel: {temp_chan.mention}", ephemeral=True)

        await asyncio.sleep(600)
        await temp_chan.delete(reason="Expired")

    except Exception as e:
        print(e)
        await interaction.followup.send("❌ Error. Make sure the bot has 'Manage Channels' permission.", ephemeral=True)

keep_alive()
bot.run(TOKEN)
