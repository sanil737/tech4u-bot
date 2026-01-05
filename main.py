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

# --- NEW ADMIN COMMAND: ANNOUNCE ---
@bot.tree.command(name="announce", description="Send a professional announcement (Admin Only)")
@app_commands.describe(channel="Where to send it", title="The heading", message="Use \\n for new lines")
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
        await interaction.response.send_message("❌ Error. Bot needs 'Send Messages' permission in that channel.", ephemeral=True)

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
        return await interaction.response.send_message("❌ Invalid or used code!", ephemeral=True)

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
        embed = discord.Embed(title="🎁 Account Details", color=discord.Color.green())
        embed.add_field(name="Service", value=f"**{item['service']}**", inline=False)
        embed.add_field(name="Email/ID", value=f"`{item['email']}`", inline=True)
        embed.add_field(name="Password", value=f"`{item['password']}`", inline=True)
        embed.description = "⏰ **This channel will delete itself in 10 minutes.**"
        
        await temp_chan.send(content=member.mention, embed=embed)

        # WEBHOOK LOG
        log = discord.Embed(title="📜 New Redemption", color=discord.Color.blue())
        log.add_field(name="User", value=f"{member.mention}", inline=True)
        log.add_field(name="Item", value=item['service'], inline=True)
        await send_webhook_log(embed=log)

        await interaction.followup.send(f"✅ Success! Check your private channel: {temp_chan.mention}", ephemeral=True)

        await asyncio.sleep(600)
        await temp_chan.delete(reason="Expired")

    except:
        await interaction.followup.send("❌ Error. Bot needs 'Manage Channels' permission.", ephemeral=True)

# --- HELP ---
@bot.tree.command(name="help", description="How to use the Tech4U system")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U Help", color=discord.Color.blue())
    embed.description = "1️⃣ Get code from GP Link\n2️⃣ Use `/redeem` here\n3️⃣ Open private channel to see info"
    await interaction.response.send_message(embed=embed)

keep_alive()
bot.run(TOKEN)
