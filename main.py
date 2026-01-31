import discord
import os
import random
import string
from discord import app_commands
from discord.ext import commands, tasks
import pymongo
from datetime import datetime, timedelta, timezone
import asyncio

# =========================================
# ⚙️ CONFIGURATION
# =========================================

TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

DB_NAME = "enjoined_gaming_ff"
ADMIN_IDS = [986251574982606888, 1458812527055212585]

# 📌 CHANNEL IDS (UPDATED)
CH_WELCOME = 1459444229255200971
CH_WARNINGS = 1459448651704303667
CH_MATCH_RESULTS = 1467146334862835966  # 📢 match-results
CH_MVP_HIGHLIGHTS = 1467148516718809149 # ⭐ mvp-highlights
CH_WEEKLY_LB = 1467148265597305046      # 📊 weekly-leaderboard
CH_FF_BET = 1467146811872641066         # 💰 free-fire-bet
CAT_MATCH_ROOMS = 1459557142850830489   # Category for private rooms

# 🛠️ SETTINGS
SYSTEM_FEE = 0.20 # 20% Fee
MIN_ENTRY = 50

# 🏅 RANK SYSTEM
RANKS = {
    "Bronze": 0, "Silver": 5, "Gold": 15, "Platinum": 30, "Diamond": 50
}

# 💙 MOTIVATION MESSAGES
MOTIVATION_QUOTES = [
    "Good motivation for the losing team. Keep grinding! 💪",
    "Close fight, keep improving 🔥",
    "Respect both players 👏",
    "Victory comes to those who train. GGs!",
    "Great performance by both sides! 🤝"
]

# =========================================
# 🗄️ DATABASE
# =========================================

mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]

col_users = db["users"]
col_matches = db["matches"]
col_settings = db["settings"]

if not col_settings.find_one({"_id": "config"}):
    col_settings.insert_one({"_id": "config", "panic": False, "locked": False})

# =========================================
# 🤖 BOT SETUP
# =========================================

class EGBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix=".", intents=intents)

    async def setup_hook(self):
        self.weekly_leaderboard_task.start()
        await self.tree.sync()
        print("✅ FF Challenge System Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")

    # 📊 WEEKLY LEADERBOARD TASK (Every 7 Days)
    @tasks.loop(hours=168)
    async def weekly_leaderboard_task(self):
        channel = self.get_channel(CH_WEEKLY_LB)
        if not channel: return

        # Get Top 10 by Wins
        top_users = col_users.find().sort("weekly_wins", -1).limit(10)
        
        embed = discord.Embed(title="📊 WEEKLY FREE FIRE LEADERBOARD", description="Top players of the week!", color=discord.Color.gold())
        
        text = ""
        for i, u in enumerate(top_users, 1):
            text += f"**{i}.** <@{u['_id']}> — 🏆 {u.get('weekly_wins', 0)} Wins\n"
        
        if not text: text = "No matches played this week."
        embed.description = text
        embed.set_footer(text="Stats reset every week!")
        
        await channel.send(embed=embed)
        
        # Reset Weekly Stats
        col_users.update_many({}, {"$set": {"weekly_wins": 0}})

bot = EGBot()

# =========================================
# 🛠️ HELPERS
# =========================================

def is_admin(user_id): return user_id in ADMIN_IDS

def get_round_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

def get_user_data(user_id):
    data = col_users.find_one({"_id": user_id})
    if not data:
        data = {
            "_id": user_id, "coins": 0, "wins": 0, "weekly_wins": 0, 
            "losses": 0, "streak": 0, "mvp_count": 0, "rank": "Bronze"
        }
        col_users.insert_one(data)
    return data

def calculate_rank(wins):
    current_rank = "Bronze"
    for r_name, r_wins in RANKS.items():
        if wins >= r_wins: current_rank = r_name
    return current_rank

# =========================================
# ⚔️ CHALLENGE SYSTEM
# =========================================

class AcceptMatchView(discord.ui.View):
    def __init__(self, challenger_id, amount, mode, round_id):
        super().__init__(timeout=300)
        self.challenger_id = challenger_id
        self.amount = amount
        self.mode = mode
        self.round_id = round_id

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        opponent = interaction.user
        challenger = interaction.guild.get_member(self.challenger_id)

        if opponent.id == self.challenger_id: return await interaction.response.send_message("❌ Cannot accept own challenge.", ephemeral=True)

        # Check Balances
        opp_data = get_user_data(opponent.id)
        chal_data = get_user_data(self.challenger_id)
        
        if opp_data["coins"] < self.amount: return await interaction.response.send_message(f"❌ You need {self.amount} EG.", ephemeral=True)
        if chal_data["coins"] < self.amount: return await interaction.response.send_message("❌ Challenger lacks funds.", ephemeral=True)

        await interaction.response.defer()

        # Deduct
        col_users.update_one({"_id": challenger.id}, {"$inc": {"coins": -self.amount}})
        col_users.update_one({"_id": opponent.id}, {"$inc": {"coins": -self.amount}})

        # Create Room
        guild = interaction.guild
        category = guild.get_channel(CAT_MATCH_ROOMS)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            challenger: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            opponent: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        for aid in ADMIN_IDS:
            m = guild.get_member(aid)
            if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True)

        chan = await guild.create_text_channel(f"ff-match-{self.round_id}", category=category, overwrites=overwrites)

        col_matches.insert_one({
            "round_id": self.round_id, "channel_id": chan.id,
            "team_a": [challenger.id], "team_b": [opponent.id],
            "mode": self.mode, "entry": self.amount, "status": "playing",
            "start_time": datetime.utcnow()
        })

        await chan.send(f"🔥 **MATCH STARTED**\n{challenger.mention} vs {opponent.mention}\nMode: {self.mode} | Bet: {self.amount} EG\n\n**Rules:**\n1. Play Fair\n2. Upload Win Screenshot\n3. Wait for Admin")
        await interaction.followup.send(f"✅ Match Created: {chan.mention}")
        self.stop()

@bot.tree.command(name="challenge", description="Start a Match")
@app_commands.describe(amount="Entry Fee", mode="1v1, 2v2...", opponent="Optional user")
async def challenge(interaction: discord.Interaction, amount: int, mode: str, opponent: discord.Member = None):
    if interaction.channel.id != CH_FF_BET:
        return await interaction.response.send_message(f"❌ Use <#{CH_FF_BET}>", ephemeral=True)
        
    if amount < MIN_ENTRY: return await interaction.response.send_message(f"❌ Min entry: {MIN_ENTRY} EG.", ephemeral=True)
    data = get_user_data(interaction.user.id)
    if data["coins"] < amount: return await interaction.response.send_message(f"❌ Low balance.", ephemeral=True)

    round_id = get_round_id()
    embed = discord.Embed(title="⚔️ NEW CHALLENGE", color=discord.Color.red())
    embed.add_field(name="Mode", value=mode)
    embed.add_field(name="Entry", value=f"{amount} EG")
    embed.add_field(name="Challenger", value=interaction.user.mention, inline=False)
    
    content = opponent.mention if opponent else "@here"
    if opponent: embed.description = f"{opponent.mention}, accept?"
    else: embed.description = "Waiting for opponent..."
    
    await interaction.response.send_message(content, embed=embed, view=AcceptMatchView(interaction.user.id, amount, mode, round_id))

# =========================================
# 👑 WINNER & SCORE CONSENT SYSTEM
# =========================================

class ScoreConsentView(discord.ui.View):
    def __init__(self, team_a_id, team_b_id):
        super().__init__(timeout=None) # Timeout handled by asyncio.sleep in main flow
        self.team_a_id = team_a_id
        self.team_b_id = team_b_id
        self.votes = {}

    @discord.ui.button(label="YES (Show Score)", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.team_a_id, self.team_b_id]:
            return await interaction.response.send_message("❌ Not your match.", ephemeral=True)
        
        self.votes[interaction.user.id] = True
        await interaction.response.send_message("✅ You voted to **SHOW** the score.", ephemeral=True)

    @discord.ui.button(label="NO (Hide Score)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.team_a_id, self.team_b_id]:
            return await interaction.response.send_message("❌ Not your match.", ephemeral=True)
        
        self.votes[interaction.user.id] = False
        await interaction.response.send_message("🚫 You voted to **HIDE** the score.", ephemeral=True)

@bot.tree.command(name="winner", description="Admin: Declare winner & score")
async def winner(interaction: discord.Interaction, winner: discord.Member, score: str, mvp: discord.Member):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    
    match = col_matches.find_one({"channel_id": interaction.channel.id})
    if not match: return await interaction.response.send_message("❌ Not a match room.", ephemeral=True)

    # 1. LOCK CHANNEL IMMEDIATELY
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    # Lock specific players
    p1 = interaction.guild.get_member(match['team_a'][0])
    p2 = interaction.guild.get_member(match['team_b'][0])
    if p1: await interaction.channel.set_permissions(p1, send_messages=False, read_messages=True)
    if p2: await interaction.channel.set_permissions(p2, send_messages=False, read_messages=True)

    await interaction.response.send_message("🔒 **Room Locked.** Starting Score Consent process...", ephemeral=True)

    # 2. ASK FOR CONSENT
    embed = discord.Embed(title="🎮 FREE FIRE MATCH RESULT (PRIVATE)", color=discord.Color.blue())
    embed.add_field(name="Match", value=f"<@{match['team_a'][0]}> vs <@{match['team_b'][0]}>")
    embed.add_field(name="Winner", value=f"🏆 {winner.mention}")
    embed.add_field(name="Score", value=score)
    embed.add_field(name="Privacy", value="💬 **Both** players must vote YES to show score publically.\nIf anyone says NO (or no reply), score is hidden.")
    embed.set_footer(text="⏳ You have 3 minutes to vote.")

    view = ScoreConsentView(match['team_a'][0], match['team_b'][0])
    vote_msg = await interaction.channel.send(f"<@{match['team_a'][0]}> <@{match['team_b'][0]}>", embed=embed, view=view)

    # 3. PROCESS REWARDS (Behind scenes)
    total_pot = match["entry"] * 2
    system_cut = int(total_pot * SYSTEM_FEE)
    prize = total_pot - system_cut

    # Update Stats
    col_users.update_one({"_id": winner.id}, {"$inc": {"coins": prize, "wins": 1, "weekly_wins": 1, "streak": 1}})
    col_users.update_one({"_id": mvp.id}, {"$inc": {"mvp_count": 1}})
    loser_id = match['team_b'][0] if match['team_a'][0] == winner.id else match['team_a'][0]
    col_users.update_one({"_id": loser_id}, {"$inc": {"losses": 1}, "$set": {"streak": 0}})

    # 4. WAIT 3 MINUTES
    await asyncio.sleep(180) 

    # 5. CHECK VOTES & POST RESULT
    show_score = False
    if view.votes.get(match['team_a'][0]) and view.votes.get(match['team_b'][0]):
        show_score = True

    # Public Result Embed
    pub_embed = discord.Embed(description="🎮 **FREE FIRE MATCH RESULT**", color=discord.Color.green())
    pub_embed.add_field(name="Players", value=f"<@{match['team_a'][0]}> vs <@{match['team_b'][0]}>", inline=False)
    pub_embed.add_field(name="Winner", value=f"🏆 {winner.mention}", inline=True)
    pub_embed.add_field(name="Entry", value=f"{match['entry']} EG", inline=True)
    
    if show_score:
        pub_embed.add_field(name="Score", value=f"**{score}**", inline=False)
        quote = random.choice(MOTIVATION_QUOTES)
        pub_embed.add_field(name="💙 Motivation", value=quote, inline=False)
    else:
        pub_embed.set_footer(text="GGs 🔥 (Score Hidden)")

    res_channel = bot.get_channel(CH_MATCH_RESULTS)
    if res_channel: await res_channel.send(embed=pub_embed)

    # MVP Highlight
    mvp_channel = bot.get_channel(CH_MVP_HIGHLIGHTS)
    if mvp_channel:
        await mvp_channel.send(f"⭐ **MVP HIGHLIGHT:** {mvp.mention} dominated in Round `{match['round_id']}`!")

    # 6. DELETE ROOM (10 Mins later)
    await interaction.channel.send("✅ Result Posted. **Deleting room in 10 minutes.**")
    col_matches.delete_one({"_id": match["_id"]})
    
    await asyncio.sleep(600) # 10 Mins
    await interaction.channel.delete()

# =========================================
# 💰 ECONOMY (Required for Betting)
# =========================================

@bot.tree.command(name="daily", description="Daily Rewards")
async def daily(interaction: discord.Interaction):
    uid = interaction.user.id
    col_users.update_one({"_id": uid}, {"$inc": {"coins": 100}}) # Simplified daily
    await interaction.response.send_message("💰 **+100 EG Coins!**")

@bot.tree.command(name="addcoins", description="Admin: Add coins")
async def addcoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return
    get_user_data(user.id)
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"✅ Added {amount} to {user.mention}")

@bot.tree.command(name="pay", description="Transfer coins")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    if amount <= 0: return
    s = get_user_data(interaction.user.id)
    if s["coins"] < amount: return await interaction.response.send_message("❌ Low balance.")
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -amount}})
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"💸 Sent {amount} to {user.mention}")

@bot.tree.command(name="profile", description="Check Stats")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    d = get_user_data(target.id)
    embed = discord.Embed(title=f"👤 {target.name}", color=discord.Color.blue())
    embed.add_field(name="💰 Coins", value=d['coins'])
    embed.add_field(name="🏆 Wins", value=d['wins'])
    embed.add_field(name="🔥 Streak", value=d['streak'])
    embed.add_field(name="⭐ MVPs", value=d['mvp_count'])
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot: return
    
    # Game Name Confirmation
    match = col_matches.find_one({"channel_id": message.channel.id})
    if match and match["status"] == "pending_game_name":
        if "free fire" in message.content.lower():
            col_matches.update_one({"_id": match["_id"]}, {"$set": {"status": "playing"}})
            await message.channel.send("✅ **Game Confirmed! Match Started.**")
            
    await bot.process_commands(message)

bot.run(TOKEN)
