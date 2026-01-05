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

# 1. PASTE YOUR WEBHOOK URL HERE
WEBHOOK_URL = "YOUR_WEBHOOK_URL_HERE"

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
    await bot.change_presence(activity=discord.Game(name="/redeem | Tech4U"))
    print(f'Logged in as {bot.user}')

# --- ADMIN: ADD CODE ---
@bot.tree.command(name="addcode", description="Add account details to a code (Admin Only)")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    data = load_data()
    data[code] = {"service": service, "email": email, "password": password}
    save_data(data)
    await interaction.response.send_message(f"✅ Code `{code}` registered for **{service}**.", ephemeral=True)

# --- USER: REDEEM (CREATES PRIVATE CHANNEL) ---
@bot.tree.command(name="redeem", description="Redeem code in a private 10-minute channel")
async def redeem(interaction: discord.Interaction, code: str):
    data = load_data()
    
    if code not in data:
        return await interaction.response.send_message("❌ Invalid or already used code!", ephemeral=True)

    # Remove code immediately
    item = data.pop(code)
    save_data(data)

    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        member = interaction.user

        # Set private permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }

        # Create Private Channel
        channel_name = f"🎁-redeem-{member.name}"
        temp_chan = await guild.create_text_channel(name=channel_name, overwrites=overwrites)

        # Create Reward Embed
        embed = discord.Embed(title="🎁 Account Details", color=discord.Color.green())
        embed.add_field(name="Service", value=f"**{item['service']}**", inline=False)
        embed.add_field(name="Email/ID", value=f"`{item['email']}`", inline=True)
        embed.add_field(name="Password", value=f"`{item['password']}`", inline=True)
        embed.description = "⚠️ **Note:** This channel will delete itself in **10 minutes**. Save your info!"
        embed.set_footer(text="Thank you for using Tech4U!")
        
        await temp_chan.send(content=member.mention, embed=embed)

        # Send Webhook Log
        log_embed = discord.Embed(title="📜 Redemption Log", color=discord.Color.blue())
        log_embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=True)
        log_embed.add_field(name="Code", value=f"`{code}`", inline=True)
        log_embed.add_field(name="Item", value=item['service'], inline=False)
        await send_webhook_log(embed=log_embed)

        await interaction.followup.send(f"✅ Code accepted! Check your private channel here: {temp_chan.mention}", ephemeral=True)

        # Delete after 10 minutes
        await asyncio.sleep(600)
        await temp_chan.delete(reason="Temporary redemption channel expired.")

    except Exception as e:
        print(f"Error: {e}")
        await interaction.followup.send("❌ Error creating channel. Make sure the bot has 'Manage Channels' permission!", ephemeral=True)

keep_alive()
bot.run(TOKEN)            log_chan = bot.get_channel(LOG_CHANNEL_ID)
            if log_chan:
                log_embed = discord.Embed(title="📜 Log: Code Redeemed", color=discord.Color.blue())
                log_embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=True)
                log_embed.add_field(name="Service", value=item['service'], inline=True)
                log_embed.add_field(name="Code", value=f"`{code}`", inline=False)
                await log_chan.send(embed=log_embed)

        await interaction.followup.send(f"✅ Code accepted! Go to {temp_channel.mention} for your account.", ephemeral=True)

        # Wait 10 minutes then delete
        await asyncio.sleep(600)
        await temp_channel.delete(reason="Temp channel expired")

    except Exception as e:
        print(e)
        await interaction.followup.send("❌ Error creating channel. Please contact an admin.", ephemeral=True)

keep_alive()
bot.run(TOKEN)
