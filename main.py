import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
from threading import Thread

# --- KEEP ALIVE SERVER FOR RENDER ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run)
    t.start()

# --- BOT CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
DATA_FILE = "codes.json"

# 1. PASTE YOUR LOG CHANNEL ID HERE (Example: 123456789012345678)
LOG_CHANNEL_ID = 1457623750475387136

def load_codes():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, "r") as f: return json.load(f)

def save_codes(codes):
    with open(DATA_FILE, "w") as f: json.dump(codes, f, indent=4)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

# --- ADMIN COMMAND: ADD CODE ---
@bot.tree.command(name="addcode", description="Add a new redeem code (Admin Only)")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    codes = load_codes()
    codes[code] = {"service": service, "email": email, "password": password}
    save_codes(codes)
    await interaction.response.send_message(f"✅ Code `{code}` added for **{service}**.", ephemeral=True)

# --- NEW ADMIN COMMAND: VIEW ALL CODES ---
@bot.tree.command(name="viewcodes", description="See all active codes in stock (Admin Only)")
async def view_codes(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    codes = load_codes()
    if not codes:
        return await interaction.response.send_message("📭 Database is empty. No codes found.", ephemeral=True)
    
    embed = discord.Embed(title="📦 Current Stock", color=discord.Color.orange())
    for c in codes:
        embed.add_field(name=f"Code: {c}", value=f"Service: {codes[c]['service']}", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- USER COMMAND: REDEEM WITH LOGS ---
@bot.tree.command(name="redeem", description="Redeem your code")
async def redeem(interaction: discord.Interaction, code: str):
    codes = load_codes()
    
    if code in codes:
        data = codes[code]
        try:
            # 1. Send Credentials to User via DM
            user_embed = discord.Embed(title="🎁 Account Redeemed!", color=discord.Color.green())
            user_embed.add_field(name="Service", value=data['service'], inline=False)
            user_embed.add_field(name="Email/ID", value=f"`{data['email']}`", inline=True)
            user_embed.add_field(name="Password", value=f"`{data['password']}`", inline=True)
            user_embed.set_footer(text="Thank you for using Tech4U!")
            await interaction.user.send(embed=user_embed)
            
            # 2. Send Log to Admin Channel
            if LOG_CHANNEL_ID != 0:
                log_chan = bot.get_channel(LOG_CHANNEL_ID)
                if log_chan:
                    log_embed = discord.Embed(title="📜 Code Redeemed", color=discord.Color.blue())
                    log_embed.add_field(name="User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=True)
                    log_embed.add_field(name="Service", value=data['service'], inline=True)
                    log_embed.add_field(name="Code Used", value=f"`{code}`", inline=False)
                    log_embed.set_timestamp()
                    await log_chan.send(embed=log_embed)

            # 3. Remove code and confirm
            del codes[code]
            save_codes(codes)
            await interaction.response.send_message("✅ Success! The details have been sent to your DMs.", ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Error: I cannot DM you. Please enable DMs in your privacy settings.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Invalid or already used code.", ephemeral=True)

keep_alive()
bot.run(TOKEN)
