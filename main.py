import discord
from discord import app_commands
from discord.ext import commands
import json
import os
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

# 1. PASTE YOUR LOG CHANNEL ID HERE
LOG_CHANNEL_ID = 1457623750475387136

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="/help | Tech4U"))
    print(f'Logged in as {bot.user}')

# --- HELP ---
@bot.tree.command(name="help", description="How to use the bot")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Tech4U System", color=discord.Color.blue())
    embed.description = "1. Get code from GP Link\n2. Use `/redeem` here\n3. Get reward in DM"
    await interaction.response.send_message(embed=embed)

# --- ADMIN: ADD CODE ---
@bot.tree.command(name="addcode", description="Add a new GP Link code (Admin Only)")
async def add_code(interaction: discord.Interaction, code: str, service_name: str, reward_details: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    data = load_data()
    data[code] = {"service": service_name, "reward": reward_details}
    save_data(data)
    await interaction.response.send_message(f"✅ Code `{code}` registered. Ready for GP Link!", ephemeral=True)

# --- USER: REDEEM (STRICT ONE-TIME) ---
@bot.tree.command(name="redeem", description="Redeem your code")
async def redeem(interaction: discord.Interaction, code: str):
    # 1. Load data
    data = load_data()
    
    # 2. Check if code exists
    if code not in data:
        return await interaction.response.send_message("❌ This code is invalid or has already been used!", ephemeral=True)

    # 3. DELETE THE CODE IMMEDIATELY (Prevents double-use)
    item = data.pop(code)
    save_data(data)

    # 4. Try to deliver the reward
    try:
        embed = discord.Embed(title="🎁 Reward Delivered!", color=discord.Color.green())
        embed.add_field(name="Item", value=item['service'], inline=False)
        embed.add_field(name="Your Reward", value=f"**{item['reward']}**", inline=False)
        embed.set_footer(text="Thank you for using Tech4U!")
        
        await interaction.user.send(embed=embed)
        
        # 5. Send Log
        if LOG_CHANNEL_ID != 0:
            log_chan = bot.get_channel(LOG_CHANNEL_ID)
            if log_chan:
                await log_chan.send(f"✅ **{interaction.user}** redeemed code `{code}` for **{item['service']}**")

        await interaction.response.send_message("✅ Success! The reward was sent to your DMs.", ephemeral=True)

    except discord.Forbidden:
        # If DMs are closed, the code is still deleted to prevent someone else from stealing it.
        await interaction.response.send_message("⚠️ Success, but I couldn't DM you! Please open your DMs and contact Admin.", ephemeral=True)

keep_alive()
bot.run(TOKEN)
