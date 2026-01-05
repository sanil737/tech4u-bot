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
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- BOT LOGIC ---
TOKEN = os.getenv("TOKEN")
DATA_FILE = "codes.json"

# Load or initialize codes
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_codes():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_codes(codes):
    with open(DATA_FILE, "w") as f:
        json.dump(codes, f, indent=4)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

# --- ADMIN COMMAND: ADD CODE ---
@bot.tree.command(name="addcode", description="Add a new redeem code (Admin Only)")
@app_commands.describe(code="The unique code", service="Service Name", email="Account Email", password="Account Password")
async def add_code(interaction: discord.Interaction, code: str, service: str, email: str, password: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You don't have permission to use this.", ephemeral=True)
        return

    codes = load_codes()
    codes[code] = {"service": service, "email": email, "password": password}
    save_codes(codes)
    
    await interaction.response.send_message(f"✅ Code `{code}` added for **{service}**.", ephemeral=True)

# --- USER COMMAND: REDEEM ---
@bot.tree.command(name="redeem", description="Redeem your service ID & Password")
@app_commands.describe(code="Enter your redeem code")
async def redeem(interaction: discord.Interaction, code: str):
    codes = load_codes()

    if code in codes:
        data = codes[code]
        try:
            # Send DM to User
            embed = discord.Embed(title="🎁 Account Redeemed!", color=discord.Color.green())
            embed.add_field(name="Service", value=data['service'], inline=False)
            embed.add_field(name="Email/ID", value=f"`{data['email']}`", inline=True)
            embed.add_field(name="Password", value=f"`{data['password']}`", inline=True)
            embed.set_footer(text="Thank you for using Tech4U!")
            
            await interaction.user.send(embed=embed)
            
            # Delete code after use
            del codes[code]
            save_codes(codes)

            await interaction.response.send_message("✅ Success! Check your DMs for account details.", ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Error: I cannot DM you. Please enable DMs in your privacy settings.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Invalid or already used code.", ephemeral=True)

keep_alive()
bot.run(TOKEN)
