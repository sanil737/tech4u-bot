import discord
import os
from discord import app_commands
from discord.ext import commands, tasks
import pymongo
from bson import ObjectId
from datetime import datetime, timedelta, timezone
import asyncio
import re
import traceback
import random
import string

# =========================================
# ⚙️ CONFIGURATION
# =========================================

TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

DB_NAME = "enjoined_gaming_db"
ADMIN_IDS = [986251574982606888, 1458812527055212585]
HELPER_ROLE_NAME = "Winner Results ⭐"
HELPER_ROLE_ID = 1467388385508462739

# 📌 CHANNELS
CH_WELCOME = 1459444229255200971
CH_FIND_TEAM = 1459469475849175304
CH_VOUCH_LOG = 1459448284530610288
CH_WARNINGS = 1459448651704303667
CH_MATCH_RESULTS = 1467146334862835966 
CH_FF_BET = 1467146811872641066
CH_MVP_HIGHLIGHTS = 1467148516718809149
CH_WEEKLY_LB = 1467148265597305046
CH_HELPER_LOG = 1467388385508462739
CAT_PRIVATE_ROOMS = 1459557142850830489
CAT_TEAM_ROOMS = 1467172386821509316
CH_CODE_USE_LOG = 1459556690536960100

# 📊 CONFIGS
PLACEMENT_POINTS = {1: 12, 2: 9, 3: 8, 4: 7, 5: 6, 6: 5, 7: 4, 8: 3, 9: 2, 10: 1}
KILL_POINT = 1
TEAM_JOIN_COST = 100
TEAM_CHANNEL_RENT = 500
SYSTEM_FEE = 0.20
MIN_ENTRY = 50
HELPER_REWARD = 10
COST_ADD_USER = 100
COST_ADD_TIME = 100

# 🏅 RANK SYSTEM
RANKS = {
    "Bronze": 0, "Silver": 5, "Gold": 15, "Platinum": 30, "Diamond": 50
}

# ⚡ BOOSTS CONFIG
BOOSTS = {
    "double_coins": {"price": 300, "name": "⚡ Double Coins", "desc": "Double win coins in next 1v1"},
    "streak_protection": {"price": 200, "name": "🛡️ Streak Protect", "desc": "Losing 1v1 won't reset streak"},
    "entry_refund": {"price": 150, "name": "💸 Entry Refund", "desc": "Get 50% back if you lose 1v1"},
    "extra_life": {"price": 250, "name": "❤️ Extra Life", "desc": "Retry a lost 1v1 (Visual)"},
    "lucky_boost": {"price": 100, "name": "🍀 Lucky Boost", "desc": "10% chance for bonus coins"},
    "coin_shield": {"price": 180, "name": "🛡️ Coin Shield", "desc": "Protect coins from risky matches"},
    "highlight": {"price": 100, "name": "⭐ Result Highlight", "desc": "Shine in #match-results"},
    "silent_comeback": {"price": 150, "name": "🎭 Silent Token", "desc": "Auto-hide score on bad loss"}
}

MOTIVATION_QUOTES = [
    "Every pro was once a beginner. Keep grinding 🔥",
    "Defeat is just a lesson. Comeback stronger 💪",
    "Respect the hustle. GGs!",
    "Close match! Well played both sides."
]

PRICES = {
    "text": {2: {1: 400, 2: 700, 4: 1200}, 3: {1: 500, 2: 900, 4: 1500}, 4: {1: 600, 2: 1100, 4: 1800}, 5: {1: 750, 2: 1300, 4: 2100}, 6: {1: 900, 2: 1500, 4: 2500}, 7: {1: 1050, 2: 1700, 4: 2800}},
    "voice": {2: {1: 500, 2: 900, 4: 1500}, 3: {1: 650, 2: 1100, 4: 1800}, 4: {1: 800, 2: 1400, 4: 2300}, 5: {1: 1000, 2: 1800, 4: 2900}, 6: {1: 1200, 2: 2100, 4: 3400}, 7: {1: 1400, 2: 2400, 4: 3900}}
}

EG_COND = """**EG cond:**\n• Respect everyone\n• Vouch after redeem\n• No abuse or spam\n• Follow admin instructions"""

# =========================================
# 🗄️ DATABASE
# =========================================

mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]

col_users = db["users"]
col_channels = db["active_channels"]
col_settings = db["settings"]
col_requests = db["pending_requests"]
col_tournaments = db["tournaments"]
col_tournament_teams = db["tournament_teams"]
col_teams = db["teams"]
col_matches = db["matches"]
col_codes = db["codes"]
col_items = db["shop_items"]
col_vouch = db["vouch_pending"]
col_invites = db["invites_tracking"]
col_giveaways = db["active_giveaways"]

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
        intents.invites = True
        super().__init__(command_prefix=".", intents=intents)
        self.invite_cache = {}

    async def setup_hook(self):
        self.check_vouch_timers.start()
        self.check_channel_expiry.start()
        self.check_request_timeouts.start()
        self.check_giveaways.start()
        self.check_team_rent.start()
        self.weekly_leaderboard_task.start()
        await self.tree.sync()
        print("✅ Commands Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")
        for guild in self.guilds:
            try:
                invs = await guild.invites()
                self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invs}
                role = discord.utils.get(guild.roles, name=HELPER_ROLE_NAME)
                if not role:
                    try: await guild.create_role(name=HELPER_ROLE_NAME, color=discord.Color.gold(), hoist=True)
                    except: pass
            except: pass

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        error_msg = str(error)
        if isinstance(error, app_commands.CommandOnCooldown):
            error_msg = f"⏳ Cooldown: {error.retry_after:.2f}s"
        elif isinstance(error, app_commands.MissingPermissions):
            error_msg = "❌ You don't have permission."
        if not interaction.response.is_done():
            await interaction.response.send_message(f"⚠️ Error: {error_msg}", ephemeral=True)

    # 🔄 TASKS
    @tasks.loop(seconds=30)
    async def check_vouch_timers(self):
        pending = list(col_vouch.find({}))
        now = datetime.now(timezone.utc)
        warning_channel = self.get_channel(CH_WARNINGS)
        for p in pending:
            try:
                start_time = p["start_time"].replace(tzinfo=timezone.utc) if p["start_time"].tzinfo is None else p["start_time"]
                elapsed = (now - start_time).total_seconds() / 60
                channel = self.get_channel(p["channel_id"])
                if not channel:
                    col_vouch.delete_one({"_id": p["_id"]})
                    continue
                user = self.get_guild(p.get("guild_id", 0)).get_member(p["user_id"]) if p.get("guild_id") else None
                if elapsed >= 10 and not p.get("warned_10"):
                    if user: await channel.send(f"⚠️ {user.mention} Reminder: 20m left to Vouch!")
                    col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_10": True}})
                elif elapsed >= 20 and not p.get("warned_20"):
                    if user: await channel.send(f"🚨 {user.mention} **FINAL WARNING**")
                    col_vouch.update_one({"_id": p["_id"]}, {"$set": {"warned_20": True}})
                elif elapsed >= 30:
                    if warning_channel and user:
                        embed = discord.Embed(title="⚠️ Failed to Vouch", description=f"{user.mention} did not vouch for **{p['service']}**.", color=discord.Color.orange())
                        await warning_channel.send(embed=embed)
                    await channel.send("🔒 Deleting...")
                    await asyncio.sleep(2)
                    await channel.delete()
                    col_vouch.delete_one({"_id": p["_id"]})
            except: pass

    @tasks.loop(hours=168)
    async def weekly_leaderboard_task(self):
        channel = self.get_channel(CH_WEEKLY_LB)
        if not channel: return
        top_players = list(col_users.find().sort("weekly_wins", -1).limit(10))
        top_teams = list(col_teams.aggregate([
            {"$lookup": {"from": "users", "localField": "members", "foreignField": "_id", "as": "member_data"}},
            {"$addFields": {"total_weekly_wins": {"$sum": "$member_data.weekly_wins"}}},
            {"$sort": {"total_weekly_wins": -1}}, {"$limit": 5}
        ]))
        embed = discord.Embed(title="⭐ WEEKLY LEADERBOARD", description="Stats reset! Rewards sent.", color=discord.Color.gold())
        p_text = ""
        for i, u in enumerate(top_players, 1):
            p_text += f"**{i}.** <@{u['_id']}> — 🏆 {u.get('weekly_wins', 0)}\n"
            reward = 150 if i==1 else 100 if i==2 else 50 if i==3 else 0
            if reward > 0: col_users.update_one({"_id": u["_id"]}, {"$inc": {"coins": reward}})
        embed.add_field(name="👤 Top Players", value=p_text if p_text else "No data.", inline=False)
        t_text = ""
        for i, t in enumerate(top_teams, 1):
            t_text += f"**{i}.** 🛡️ {t['name']} — 🏆 {t.get('total_weekly_wins', 0)}\n"
            reward = 150 if i==1 else 100 if i==2 else 50 if i==3 else 0
            if reward > 0: col_users.update_many({"_id": {"$in": t["members"]}}, {"$inc": {"coins": reward}})
        embed.add_field(name="👥 Top Teams", value=t_text if t_text else "No data.", inline=False)
        await channel.send(embed=embed)
        col_users.update_many({}, {"$set": {"weekly_wins": 0}})

    @tasks.loop(hours=6)
    async def check_team_rent(self):
        teams = col_teams.find({})
        now = datetime.now(timezone.utc)
        for team in teams:
            if "rent_expiry" in team and team["channel_id"]:
                expiry = team["rent_expiry"].replace(tzinfo=timezone.utc) if team["rent_expiry"].tzinfo is None else team["rent_expiry"]
                if now > expiry:
                    channel = self.get_channel(team["channel_id"])
                    if channel:
                        await channel.set_permissions(channel.guild.default_role, send_messages=False)
                        for member_id in team["members"]:
                            mem = channel.guild.get_member(member_id)
                            if mem: await channel.set_permissions(mem, read_messages=True, send_messages=False)
                        try: await channel.send(f"⚠️ **Rent Expired!**\nUse `/payteamrent` (Cost: {TEAM_CHANNEL_RENT}) to unlock.")
                        except: pass

    @tasks.loop(seconds=60)
    async def check_channel_expiry(self):
        active = list(col_channels.find({}))
        now = datetime.now(timezone.utc)
        for c in active:
            try:
                end_time = c["end_time"].replace(tzinfo=timezone.utc) if c["end_time"].tzinfo is None else c["end_time"]
                if now > end_time:
                    channel = self.get_channel(c["channel_id"])
                    if channel: await channel.delete()
                    col_users.update_one({"_id": c["owner_id"]}, {"$set": {"current_private_channel_id": None}})
                    col_channels.delete_one({"_id": c["_id"]})
            except: pass

    @tasks.loop(minutes=1)
    async def check_giveaways(self):
        active = col_giveaways.find({})
        now = datetime.now(timezone.utc)
        for gw in active:
            end = gw["end_time"].replace(tzinfo=timezone.utc) if gw["end_time"].tzinfo is None else gw["end_time"]
            if now >= end:
                ch = self.get_channel(gw["channel_id"])
                if ch:
                    try:
                        msg = await ch.fetch_message(gw["message_id"])
                        guild = ch.guild
                        valid = [u for u in gw["entries"] if guild.get_member(u)]
                        if valid:
                            win = random.choice(valid)
                            await msg.reply(f"🎉 Winner: <@{win}> | Prize: **{gw['prize']}**")
                        else: await msg.reply("❌ No valid entries.")
                    except: pass
                col_giveaways.delete_one({"_id": gw["_id"]})

    @tasks.loop(minutes=10)
    async def check_invite_validation(self):
        pending = col_invites.find({"valid": False})
        now = datetime.now(timezone.utc)
        for inv in pending:
            join = inv["joined_at"].replace(tzinfo=timezone.utc) if inv["joined_at"].tzinfo is None else inv["joined_at"]
            if now > (join + timedelta(hours=24)):
                col_invites.update_one({"_id": inv["_id"]}, {"$set": {"valid": True}})
                col_users.update_one({"_id": inv["inviter_id"]}, {"$inc": {"coins": 100, "invite_count": 1}})

    @tasks.loop(minutes=1)
    async def check_request_timeouts(self):
        reqs = col_requests.find({})
        now = datetime.now(timezone.utc)
        for r in reqs:
            expire = r["expires_at"].replace(tzinfo=timezone.utc) if r["expires_at"].tzinfo is None else r["expires_at"]
            if now > expire:
                col_users.update_one({"_id": r["host_id"]}, {"$inc": {"coins": r["price"]}})
                col_requests.delete_one({"_id": r["_id"]})

bot = EGBot()

def is_admin(user_id): return user_id in ADMIN_IDS

def is_helper(interaction: discord.Interaction):
    if interaction.user.id in ADMIN_IDS: return True
    if interaction.guild:
        role = discord.utils.get(interaction.guild.roles, name=HELPER_ROLE_NAME)
        if role and role in interaction.user.roles: return True
    return False

def get_user_data(user_id):
    data = col_users.find_one({"_id": user_id})
    if not data:
        data = {"_id": user_id, "coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None, "invite_count": 0, "boosts": {}, "team_id": None, "wins": 0, "losses": 0, "weekly_wins": 0, "streak": 0, "mvp_count": 0, "rank": "Bronze", "history": []}
        col_users.insert_one(data)
    updates = {}
    if "boosts" not in data: updates["boosts"] = {}
    if "rank" not in data: updates["rank"] = "Bronze"
    if "history" not in data: updates["history"] = []
    if updates: col_users.update_one({"_id": user_id}, {"$set": updates})
    return data

def calculate_rank(wins):
    current_rank = "Bronze"
    for r_name, r_wins in RANKS.items():
        if wins >= r_wins: current_rank = r_name
    return current_rank

async def delayed_helper_reward(user_id):
    # Security: Wait 1-3 mins before giving reward so they can't trace it to specific match instantly
    await asyncio.sleep(random.randint(60, 180))
    col_users.update_one({"_id": user_id}, {"$inc": {"coins": HELPER_REWARD}})

async def update_main_message(channel, owner_id, end_time):
    c_data = col_channels.find_one({"channel_id": channel.id})
    if not c_data or "main_msg_id" not in c_data: return
    try:
        msg = await channel.fetch_message(c_data["main_msg_id"])
        members = [m.mention for m in channel.members if not m.bot]
        joined_str = ", ".join(members)
        timestamp = int(end_time.timestamp())
        content = (f"🔒 **Private Channel**\n👑 **Owner:** <@{owner_id}>\n👥 **Joined:** {joined_str}\n⏰ **Expires:** <t:{timestamp}:R>\n\n➕ **Upgrades:**\n`/adduser @user` (100 coins)\n`/addtime hours` (100 coins/hr)")
        await msg.edit(content=content)
    except: pass

# =========================================
# 🛡️ ADMIN / HELPER COMMANDS
# =========================================

@bot.tree.command(name="makerole", description="Create the Helper role")
async def makerole(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    role = discord.utils.get(interaction.guild.roles, name=HELPER_ROLE_NAME)
    if role: return await interaction.response.send_message("✅ Role exists.", ephemeral=True)
    await interaction.guild.create_role(name=HELPER_ROLE_NAME, color=discord.Color.gold(), hoist=True)
    await interaction.response.send_message(f"✅ Created role: **{HELPER_ROLE_NAME}**", ephemeral=True)

@bot.tree.command(name="make", description="Give a user the Helper role")
async def make(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    role = discord.utils.get(interaction.guild.roles, name=HELPER_ROLE_NAME)
    if not role: return await interaction.response.send_message(f"❌ Role not found. Run `/makerole`.", ephemeral=True)
    await user.add_roles(role)
    await interaction.response.send_message(f"✅ {user.mention} is now a Helper!", ephemeral=True)

@bot.tree.command(name="winner", description="Submit Match Result")
async def winner(interaction: discord.Interaction, gameid: str, winner: discord.Member, score: str):
    if not is_helper(interaction): return await interaction.response.send_message("❌ Admin/Helper only.", ephemeral=True)
    
    match = col_matches.find_one({"round_id": gameid})
    if not match: return await interaction.response.send_message(f"❌ Match ID `{gameid}` not found.", ephemeral=True)
    
    # 1. Start Score Consent
    loser_id = match['team_b'][0] if match['team_a'][0] == winner.id else match['team_a'][0]
    
    view = ScoreConsentView(match['team_a'][0], match['team_b'][0], winner.id, score, gameid, interaction.user.id)
    await interaction.response.send_message(f"🏁 **Result Submitted!**\n🏆 Winner: {winner.mention}\n📊 Score: {score}\n\n⚠️ Players must confirm score visibility.", view=view)
    
    # 2. Wait for votes or timeout
    await asyncio.sleep(120)
    
    # 3. Finalize if not already done
    if not view.finalized:
        await process_match_result(interaction, match, winner.id, score, interaction.user.id, show_score=False)

class ScoreConsentView(discord.ui.View):
    def __init__(self, p1, p2, winner, score, gameid, helper):
        super().__init__(timeout=None)
        self.p1 = p1
        self.p2 = p2
        self.winner = winner
        self.score = score
        self.gameid = gameid
        self.helper = helper
        self.votes = {}
        self.finalized = False

    async def check_votes(self, interaction):
        if self.votes.get(self.p1) and self.votes.get(self.p2):
            self.finalized = True
            await process_match_result(interaction, col_matches.find_one({"round_id": self.gameid}), self.winner, self.score, self.helper, show_score=True)
        elif False in self.votes.values():
            self.finalized = True
            await process_match_result(interaction, col_matches.find_one({"round_id": self.gameid}), self.winner, self.score, self.helper, show_score=False)

    @discord.ui.button(label="✅ Show Score", style=discord.ButtonStyle.green)
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1, self.p2]: return
        self.votes[interaction.user.id] = True
        await interaction.response.send_message("✅ Voted to Show.", ephemeral=True)
        await self.check_votes(interaction)

    @discord.ui.button(label="❌ Hide Score", style=discord.ButtonStyle.red)
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1, self.p2]: return
        self.votes[interaction.user.id] = False
        await interaction.response.send_message("🚫 Voted to Hide.", ephemeral=True)
        await self.check_votes(interaction)

    @discord.ui.button(label="❗ Report Issue", style=discord.ButtonStyle.danger)
    async def report(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1, self.p2]: return
        self.finalized = True # Stop auto post
        warn = interaction.guild.get_channel(CH_WARNINGS)
        if warn: await warn.send(f"🚨 **DISPUTE**\nGame: {self.gameid}\nUser: {interaction.user.mention}")
        await interaction.response.send_message("🛑 Match Paused. Admins Notified.")

async def process_match_result(interaction, match_data, winner_id, score, helper_id, show_score):
    if not match_data: return
    
    # 1. Helper Reward (Secret Delay)
    if helper_id not in ADMIN_IDS:
        asyncio.create_task(delayed_helper_reward(helper_id))
        log_chan = bot.get_channel(CH_HELPER_LOG)
        if log_chan: await log_chan.send(f"🔐 **Log**\nID: {match_data['round_id']}\nHelper: <@{helper_id}>\nReward: +10 (Pending)")

    # 2. Update Stats
    loser_id = match_data['team_b'][0] if match_data['team_a'][0] == winner_id else match_data['team_a'][0]
    pot = match_data["entry"] * 2
    prize = int(pot * (1 - SYSTEM_FEE))

    # Winner Logic
    win_user = get_user_data(winner_id)
    if win_user['boosts'].get('double_coins'):
        prize *= 2
        col_users.update_one({"_id": winner_id}, {"$unset": {"boosts.double_coins": ""}})
    
    new_wins = win_user["wins"] + 1
    new_rank = calculate_rank(new_wins)
    col_users.update_one({"_id": winner_id}, {"$inc": {"coins": prize, "wins": 1, "weekly_wins": 1, "streak": 1}, "$set": {"rank": new_rank}})

    # Loser Logic
    lose_user = get_user_data(loser_id)
    if lose_user['boosts'].get('entry_refund'):
        col_users.update_one({"_id": loser_id}, {"$inc": {"coins": int(match_data['entry'] * 0.5)}, "$unset": {"boosts.entry_refund": ""}})
    
    if not lose_user['boosts'].get('streak_protection'):
        col_users.update_one({"_id": loser_id}, {"$inc": {"losses": 1}, "$set": {"streak": 0}})
    else:
        col_users.update_one({"_id": loser_id}, {"$unset": {"boosts.streak_protection": ""}})

    # Silent Comeback Check
    if lose_user['boosts'].get('silent_comeback'):
        show_score = False
        col_users.update_one({"_id": loser_id}, {"$unset": {"boosts.silent_comeback": ""}})

    # Match History
    ts = datetime.now(timezone.utc)
    col_users.update_one({"_id": winner_id}, {"$push": {"history": {"res": "W", "vs": loser_id, "s": score, "t": ts}}})
    col_users.update_one({"_id": loser_id}, {"$push": {"history": {"res": "L", "vs": winner_id, "s": score, "t": ts}}})

    # 3. Public Post
    res_chan = bot.get_channel(CH_MATCH_RESULTS)
    if res_chan:
        # Highlight Boost
        is_highlight = win_user['boosts'].get('highlight')
        color = discord.Color.gold() if is_highlight else discord.Color.green()
        title = "🌟 MATCH RESULT" if is_highlight else "🏁 MATCH RESULT"
        if is_highlight: col_users.update_one({"_id": winner_id}, {"$unset": {"boosts.highlight": ""}})

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="🏆 Winner", value=f"<@{winner_id}>", inline=True)
        embed.add_field(name="📊 Score", value=f"**{score}**" if show_score else "||Hidden||", inline=True)
        embed.add_field(name="⚔️ Match", value=f"<@{match_data['team_a'][0]}> vs <@{match_data['team_b'][0]}>", inline=False)
        embed.set_footer(text=random.choice(MOTIVATION_QUOTES))
        await res_chan.send(embed=embed)

    # 4. Clean Room
    try: await interaction.channel.send("✅ **Result Posted.** Deleting in 10s...")
    except: pass
    col_matches.delete_one({"_id": match_data["_id"]})
    await asyncio.sleep(10)
    try: await interaction.channel.delete()
    except: pass

@bot.tree.command(name="lock", description="Admin: Lock")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    if "redeem-" in interaction.channel.name or "buy-" in interaction.channel.name: return await interaction.response.send_message("❌ Cannot lock Redeem channels.", ephemeral=True)
    if col_channels.find_one({"channel_id": interaction.channel.id}): return await interaction.response.send_message("❌ Cannot lock Private channels.", ephemeral=True)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Locked.")

@bot.tree.command(name="unlock", description="Admin: Unlock")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None)
    await interaction.response.send_message("🔓 Unlocked.")

@bot.tree.command(name="ann", description="Admin: Announce")
async def ann(interaction: discord.Interaction, title: str, message: str, channel: discord.TextChannel = None):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    target = channel or interaction.channel
    await target.send(embed=discord.Embed(title=title, description=message, color=discord.Color.blue()))
    await interaction.response.send_message("✅ Sent", ephemeral=True)

@bot.tree.command(name="clear", description="Admin: Clear")
async def clear(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction.user.id): return
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=min(amount, 100))
    await interaction.followup.send("🧹 Done", ephemeral=True)

@bot.tree.command(name="panic", description="Admin: Panic")
async def panic(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    c = col_settings.find_one({"_id": "config"})
    col_settings.update_one({"_id": "config"}, {"$set": {"panic": not c["panic"]}})
    await interaction.response.send_message(f"🚨 Panic: {not c['panic']}", ephemeral=True)

@bot.tree.command(name="removecoins", description="Admin: Remove coins")
async def removecoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": -amount}})
    await interaction.response.send_message(f"✅ Removed {amount} from {user.mention}", ephemeral=True)

@bot.tree.command(name="addcoins", description="Admin: Add coins")
async def addcoins(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    get_user_data(user.id)
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"✅ Added {amount} to {user.mention}", ephemeral=True)

@bot.tree.command(name="warn", description="Admin: Warn a user")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    try: await user.send(f"⚠️ **Warned in {interaction.guild.name}**\nReason: {reason}")
    except: pass
    warn_channel = bot.get_channel(CH_WARNINGS)
    if warn_channel:
        embed = discord.Embed(title="⚠️ User Warned", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=True)
        embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await warn_channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Warned {user.mention}.", ephemeral=True)

@bot.tree.command(name="leaderboard", description="View Weekly Leaderboard")
async def leaderboard(interaction: discord.Interaction):
    if interaction.channel.id != CH_WEEKLY_LB:
        return await interaction.response.send_message(f"❌ Use <#{CH_WEEKLY_LB}>", ephemeral=True)

    await interaction.response.defer()
    top_players = list(col_users.find().sort("weekly_wins", -1).limit(10))
    top_teams = list(col_teams.aggregate([
        {"$lookup": {"from": "users", "localField": "members", "foreignField": "_id", "as": "member_data"}},
        {"$addFields": {"total_weekly_wins": {"$sum": "$member_data.weekly_wins"}}},
        {"$sort": {"total_weekly_wins": -1}}, {"$limit": 5}
    ]))

    embed = discord.Embed(title="⭐ WEEKLY LEADERBOARD", color=discord.Color.gold())
    
    p_text = ""
    for i, u in enumerate(top_players, 1):
        p_text += f"**{i}.** <@{u['_id']}> — 🏆 {u.get('weekly_wins', 0)}\n"
    
    embed.add_field(name="👤 Top Players", value=p_text if p_text else "No data.", inline=False)
    
    t_text = ""
    for i, t in enumerate(top_teams, 1):
        t_text += f"**{i}.** 🛡️ {t['name']} — 🏆 {t.get('total_weekly_wins', 0)}\n"
    
    embed.add_field(name="👥 Top Teams", value=t_text if t_text else "No data.", inline=False)
    embed.set_footer(text="Updates live. Resets Sundays.")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="status", description="Balance")
async def status(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💳 {d['coins']} Coins", ephemeral=True)

@bot.tree.command(name="profile", description="Check stats")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    d = get_user_data(target.id) 
    embed = discord.Embed(title=f"👤 {target.name}'s Profile", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="💰 Coins", value=d.get('coins', 0))
    embed.add_field(name="🏆 Wins", value=d.get('wins', 0))
    embed.add_field(name="🏅 Rank", value=d.get('rank', 'Bronze'))
    
    team_name = "None"
    if d.get("team_id"):
        team = col_teams.find_one({"_id": d["team_id"]})
        if team: team_name = team["name"]
    embed.add_field(name="🛡️ Team", value=team_name, inline=False)
    
    # History
    history = d.get('history', [])[-3:]
    h_text = ""
    for h in reversed(history):
        r = "✅" if h['res'] == "W" else "❌"
        h_text += f"{r} vs <@{h['vs']}>\n"
    if h_text: embed.add_field(name="📜 Last 3 Matches", value=h_text, inline=False)

    boosts = d.get('boosts', {})
    active = [BOOSTS[k]['name'] for k, v in boosts.items() if v]
    if active: embed.add_field(name="⚡ Active Boosts", value="\n".join(active), inline=False)
    await interaction.response.send_message(embed=embed)

# =========================================
# ⚔️ 1v1 MATCH
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
        
        col_users.update_one({"_id": challenger.id}, {"$inc": {"coins": -self.amount}})
        col_users.update_one({"_id": opponent.id}, {"$inc": {"coins": -self.amount}})

        guild = interaction.guild
        category = guild.get_channel(CAT_PRIVATE_ROOMS) 
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            challenger: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            opponent: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        chan = await guild.create_text_channel(f"match-{self.round_id}", category=category, overwrites=overwrites)

        col_matches.insert_one({
            "round_id": self.round_id, "channel_id": chan.id,
            "team_a": [challenger.id], "team_b": [opponent.id],
            "mode": self.mode, "entry": self.amount, "status": "playing"
        })

        await chan.send(f"🔥 **MATCH STARTED**\n{challenger.mention} vs {opponent.mention}\nBet: {self.amount} EG\n🆔 Round ID: `{self.round_id}`")
        await interaction.followup.send(f"✅ Match Created: {chan.mention}")
        self.stop()

@bot.tree.command(name="challenge", description="Start a Match")
@app_commands.describe(amount="Entry Fee", mode="1v1, 2v2...", opponent="Optional user")
async def challenge(interaction: discord.Interaction, amount: int, mode: str, opponent: discord.Member = None):
    if interaction.channel.id != CH_FF_BET: return await interaction.response.send_message(f"❌ Use <#{CH_FF_BET}>", ephemeral=True)
    if amount < MIN_ENTRY: return await interaction.response.send_message(f"❌ Min: {MIN_ENTRY} EG.", ephemeral=True)
    data = get_user_data(interaction.user.id)
    if data["coins"] < amount: return await interaction.response.send_message(f"❌ Low balance.", ephemeral=True)

    round_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    embed = discord.Embed(title="⚔️ NEW CHALLENGE", color=discord.Color.red())
    embed.add_field(name="Mode", value=mode)
    embed.add_field(name="Entry", value=f"{amount} EG")
    embed.add_field(name="Challenger", value=interaction.user.mention, inline=False)
    content = opponent.mention if opponent else "@here"
    await interaction.response.send_message(content, embed=embed, view=AcceptMatchView(interaction.user.id, amount, mode, round_id))

class BoostShopView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    async def process_buy(self, interaction: discord.Interaction, boost_key: str):
        uid = interaction.user.id
        data = get_user_data(uid)
        cost = BOOSTS[boost_key]["price"]
        name = BOOSTS[boost_key]["name"]
        if data["coins"] < cost: return await interaction.response.send_message(f"❌ Need {cost} coins!", ephemeral=True)
        col_users.update_one({"_id": uid}, {"$inc": {"coins": -cost}, "$set": {f"boosts.{boost_key}": True}})
        await interaction.response.send_message(f"✅ Purchased **{name}**!", ephemeral=True)
    @discord.ui.button(label="⚡ Double Coins (300)", style=discord.ButtonStyle.primary, custom_id="buy_double")
    async def buy_double(self, interaction, button): await self.process_buy(interaction, "double_coins")
    @discord.ui.button(label="🛡️ Streak Protect (200)", style=discord.ButtonStyle.success, custom_id="buy_streak")
    async def buy_streak(self, interaction, button): await self.process_buy(interaction, "streak_protection")
    @discord.ui.button(label="💸 Refund (150)", style=discord.ButtonStyle.secondary, custom_id="buy_refund")
    async def buy_refund(self, interaction, button): await self.process_buy(interaction, "entry_refund")
    @discord.ui.button(label="❤️ Extra Life (250)", style=discord.ButtonStyle.danger, custom_id="buy_life")
    async def buy_life(self, interaction, button): await self.process_buy(interaction, "extra_life")
    @discord.ui.button(label="🍀 Lucky Boost (100)", style=discord.ButtonStyle.success, custom_id="buy_lucky")
    async def buy_lucky(self, interaction, button): await self.process_buy(interaction, "lucky_boost")
    @discord.ui.button(label="🛡️ Coin Shield (180)", style=discord.ButtonStyle.primary, custom_id="buy_shield")
    async def buy_shield(self, interaction, button): await self.process_buy(interaction, "coin_shield")

@bot.tree.command(name="boostshop", description="Open Boost Shop")
async def boostshop(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    embed = discord.Embed(title="🎮 EG Boost Shop", description=f"**Your Coins:** 💰 {d['coins']}\n\n🛒 **Available Boosts:**", color=discord.Color.gold())
    text = ""
    for k, v in BOOSTS.items(): text += f"**{v['name']}** • `💰 {v['price']}`\n{v['desc']}\n\n"
    embed.add_field(name="Boost List", value=text)
    await interaction.response.send_message(embed=embed, view=BoostShopView())

@bot.tree.command(name="buy_boost", description="Buy boost")
@app_commands.choices(boost=[app_commands.Choice(name=f"{k.replace('_', ' ').title()} ({v['price']})", value=k) for k, v in BOOSTS.items()])
async def buy_boost(interaction: discord.Interaction, boost: str):
    data = get_user_data(interaction.user.id)
    cost = BOOSTS[boost]["price"]
    if data["coins"] < cost: return await interaction.response.send_message(f"❌ Need {cost} coins.", ephemeral=True)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -cost}, "$set": {f"boosts.{boost}": True}})
    await interaction.response.send_message(f"✅ Purchased **{boost}**!", ephemeral=True)

class AddUserView(discord.ui.View):
    def __init__(self, target_id, owner_id, cost, channel_id):
        super().__init__(timeout=300)
        self.target_id = target_id
        self.owner_id = owner_id
        self.cost = cost
        self.channel_id = channel_id
    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id: return await interaction.response.send_message("❌ Not for you.", ephemeral=True)
        owner_data = get_user_data(self.owner_id)
        if owner_data["coins"] < self.cost: return await interaction.response.send_message("❌ Owner out of coins!", ephemeral=True)
        col_users.update_one({"_id": self.owner_id}, {"$inc": {"coins": -self.cost}})
        await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True, connect=True, speak=True)
        await interaction.response.send_message(f"✅ Joined!", ephemeral=False)
        c_data = col_channels.find_one({"channel_id": self.channel_id})
        if c_data:
            end_time = c_data["end_time"].replace(tzinfo=timezone.utc) if c_data["end_time"].tzinfo is None else c_data["end_time"]
            await update_main_message(interaction.channel, self.owner_id, end_time)
        self.stop()
    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id: return
        await interaction.channel.set_permissions(interaction.user, overwrite=None)
        await interaction.response.send_message(f"❌ Declined.", ephemeral=False)
        self.stop()

@bot.tree.command(name="adduser", description="Add user to private room (100 coins)")
async def adduser(interaction: discord.Interaction, user: discord.Member):
    c_data = col_channels.find_one({"channel_id": interaction.channel.id})
    if not c_data or interaction.user.id != c_data["owner_id"]: return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
    if user.id == interaction.user.id or user.bot: return await interaction.response.send_message("❌ Invalid.", ephemeral=True)
    data = get_user_data(interaction.user.id)
    if data["coins"] < COST_ADD_USER: return await interaction.response.send_message(f"❌ Need {COST_ADD_USER} coins.", ephemeral=True)
    await interaction.channel.set_permissions(user, read_messages=True, send_messages=False, connect=False)
    end_time = c_data["end_time"].replace(tzinfo=timezone.utc) if c_data["end_time"].tzinfo is None else c_data["end_time"]
    timestamp = int(end_time.timestamp())
    msg = f"📩 **Invite**\n👑 Owner: {interaction.user.mention}\n⏰ Left: <t:{timestamp}:R>\n{user.mention}, accept?"
    await interaction.response.send_message(msg, view=AddUserView(user.id, interaction.user.id, COST_ADD_USER, interaction.channel.id))

@bot.tree.command(name="addtime", description="Extend room time (100/hr)")
async def addtime(interaction: discord.Interaction, hours: int):
    c_data = col_channels.find_one({"channel_id": interaction.channel.id})
    if not c_data or interaction.user.id != c_data["owner_id"]: return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
    if hours < 1: return await interaction.response.send_message("❌ Min 1h.", ephemeral=True)
    cost = hours * COST_ADD_TIME
    data = get_user_data(interaction.user.id)
    if data["coins"] < cost: return await interaction.response.send_message(f"❌ Need {cost} coins.", ephemeral=True)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -cost}})
    current_end = c_data["end_time"].replace(tzinfo=timezone.utc) if c_data["end_time"].tzinfo is None else c_data["end_time"]
    new_end = current_end + timedelta(hours=hours)
    col_channels.update_one({"_id": c_data["_id"]}, {"$set": {"end_time": new_end}})
    await interaction.response.send_message(f"✅ Added {hours}h!")
    await update_main_message(interaction.channel, interaction.user.id, new_end)

@bot.tree.command(name="prices", description="Show private channel prices")
async def prices(interaction: discord.Interaction):
    embed = discord.Embed(title="🏷️ Pricing", color=discord.Color.gold())
    t = ""
    for u, c in PRICES["text"].items(): t += f"**{u}**: 1h {c[1]} | 2h {c[2]} | 4h {c[4]}\n"
    embed.add_field(name="Text", value=t)
    v = ""
    for u, c in PRICES["voice"].items(): v += f"**{u}**: 1h {c[1]} | 2h {c[2]} | 4h {c[4]}\n"
    embed.add_field(name="Voice", value=v)
    await interaction.response.send_message(embed=embed)

# =========================================
# 🛡️ TEAM SYSTEM
# =========================================

@bot.tree.command(name="deleteteam", description="Leader: Delete your team")
async def deleteteam(interaction: discord.Interaction):
    uid = interaction.user.id
    data = get_user_data(uid)
    if not data.get("team_id"): return await interaction.response.send_message("❌ Not in a team.", ephemeral=True)
    team = col_teams.find_one({"_id": data["team_id"]})
    if team["leader_id"] != uid: return await interaction.response.send_message("❌ Leader only.", ephemeral=True)
    
    chan = interaction.guild.get_channel(team["channel_id"])
    if chan: await chan.delete()
    
    col_users.update_many({"team_id": team["_id"]}, {"$set": {"team_id": None}})
    col_teams.delete_one({"_id": team["_id"]})
    await interaction.response.send_message(f"✅ Team **{team['name']}** deleted.", ephemeral=True)

@bot.tree.command(name="removemembersteam", description="Leader: Remove member")
async def removemembersteam(interaction: discord.Interaction, user: discord.Member):
    uid = interaction.user.id
    data = get_user_data(uid)
    if not data.get("team_id"): return await interaction.response.send_message("❌ Not in a team.", ephemeral=True)
    team = col_teams.find_one({"_id": data["team_id"]})
    if team["leader_id"] != uid: return await interaction.response.send_message("❌ Leader only.", ephemeral=True)
    if user.id not in team["members"]: return await interaction.response.send_message("❌ User not in team.", ephemeral=True)
    if user.id == uid: return await interaction.response.send_message("❌ Cannot remove self.", ephemeral=True)
    col_teams.update_one({"_id": team["_id"]}, {"$pull": {"members": user.id}})
    col_users.update_one({"_id": user.id}, {"$set": {"team_id": None}})
    chan = interaction.guild.get_channel(team["channel_id"])
    if chan: await chan.set_permissions(user, overwrite=None); await chan.send(f"👋 {user.mention} removed.")
    await interaction.response.send_message(f"✅ Removed {user.name}.", ephemeral=True)

@bot.tree.command(name="leave", description="Leave your team")
async def leave(interaction: discord.Interaction):
    uid = interaction.user.id
    data = get_user_data(uid)
    if not data.get("team_id"): return await interaction.response.send_message("❌ Not in a team.", ephemeral=True)
    team = col_teams.find_one({"_id": data["team_id"]})
    if team["leader_id"] == uid: return await interaction.response.send_message("❌ Leader cannot leave (use /deleteteam).", ephemeral=True)
    col_teams.update_one({"_id": team["_id"]}, {"$pull": {"members": uid}})
    col_users.update_one({"_id": uid}, {"$set": {"team_id": None}})
    chan = interaction.guild.get_channel(team["channel_id"])
    if chan: await chan.set_permissions(interaction.user, overwrite=None); await chan.send(f"👋 {interaction.user.mention} left.")
    await interaction.response.send_message(f"✅ Left {team['name']}.", ephemeral=True)

@bot.tree.command(name="createteam", description="Create a team (Max 6 members)")
async def createteam(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    uid = interaction.user.id
    user_data = get_user_data(uid)
    if user_data.get("team_id"): return await interaction.followup.send("❌ Already in a team.")
    if col_teams.find_one({"name": name}): return await interaction.followup.send("❌ Taken.")
    guild = interaction.guild
    cat = guild.get_channel(CAT_TEAM_ROOMS)
    overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True), guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True)}
    for aid in ADMIN_IDS:
        m = guild.get_member(aid)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True)
    chan = await guild.create_text_channel(f"🛡️-{name.lower()}", category=cat, overwrites=overwrites)
    team_id = ObjectId()
    rent_expiry = datetime.now(timezone.utc) + timedelta(days=7)
    col_teams.insert_one({"_id": team_id, "name": name, "leader_id": uid, "members": [uid], "channel_id": chan.id, "rent_expiry": rent_expiry, "join_requests": []})
    col_users.update_one({"_id": uid}, {"$set": {"team_id": team_id}})
    await chan.send(f"🛡️ **Team {name} Created!**\n👑 Leader: {interaction.user.mention}\n⏰ Rent Expires: <t:{int(rent_expiry.timestamp())}:R>")
    await interaction.followup.send(f"✅ Team created! {chan.mention}")

@bot.tree.command(name="jointeam", description="Request to join a team (100 coins)")
async def jointeam(interaction: discord.Interaction, team_name: str):
    uid = interaction.user.id
    data = get_user_data(uid)
    if data.get("team_id"): return await interaction.response.send_message("❌ Already in a team.", ephemeral=True)
    if data["coins"] < TEAM_JOIN_COST: return await interaction.response.send_message(f"❌ Need {TEAM_JOIN_COST} coins.", ephemeral=True)
    team = col_teams.find_one({"name": team_name})
    if not team: return await interaction.response.send_message("❌ Team not found.", ephemeral=True)
    if len(team["members"]) >= 6: return await interaction.response.send_message("❌ Team full.", ephemeral=True)
    if uid in team.get("join_requests", []): return await interaction.response.send_message("❌ Request already sent.", ephemeral=True)
    col_teams.update_one({"_id": team["_id"]}, {"$push": {"join_requests": uid}})
    col_users.update_one({"_id": uid}, {"$inc": {"coins": -TEAM_JOIN_COST}})
    leader = interaction.guild.get_member(team["leader_id"])
    if leader:
        try: await leader.send(f"📩 **Join Request:** {interaction.user.name} wants to join **{team['name']}**.\nUse `/acceptjoin @user`.")
        except: pass
    await interaction.response.send_message(f"✅ Request sent to **{team_name}**.", ephemeral=True)

@bot.tree.command(name="acceptjoin", description="Leader: Accept join request")
async def acceptjoin(interaction: discord.Interaction, user: discord.Member):
    uid = interaction.user.id
    data = get_user_data(uid)
    if not data.get("team_id"): return await interaction.response.send_message("❌ Not in a team.", ephemeral=True)
    team = col_teams.find_one({"_id": data["team_id"]})
    if team["leader_id"] != uid: return await interaction.response.send_message("❌ Leader only.", ephemeral=True)
    if user.id not in team.get("join_requests", []): return await interaction.response.send_message("❌ No request found.", ephemeral=True)
    col_teams.update_one({"_id": team["_id"]}, {"$pull": {"join_requests": user.id}, "$push": {"members": user.id}})
    col_users.update_one({"_id": user.id}, {"$set": {"team_id": team["_id"]}})
    chan = interaction.guild.get_channel(team["channel_id"])
    if chan:
        await chan.set_permissions(user, read_messages=True, send_messages=True)
        await chan.send(f"👋 Welcome {user.mention}!")
    await interaction.response.send_message(f"✅ {user.name} accepted.")

@bot.tree.command(name="payteamrent", description="Pay 500 coins for 7 days chat")
async def payteamrent(interaction: discord.Interaction):
    uid = interaction.user.id
    data = get_user_data(uid)
    if not data.get("team_id"): return await interaction.response.send_message("❌ Not in a team.", ephemeral=True)
    if data["coins"] < TEAM_CHANNEL_RENT: return await interaction.response.send_message(f"❌ Need {TEAM_CHANNEL_RENT} coins.", ephemeral=True)
    team = col_teams.find_one({"_id": data["team_id"]})
    current_expiry = team.get("rent_expiry")
    now = datetime.now(timezone.utc)
    if current_expiry and current_expiry.tzinfo is None: current_expiry = current_expiry.replace(tzinfo=timezone.utc)
    if not current_expiry or current_expiry < now: new_expiry = now + timedelta(days=7)
    else: new_expiry = current_expiry + timedelta(days=7)
    col_users.update_one({"_id": uid}, {"$inc": {"coins": -TEAM_CHANNEL_RENT}})
    col_teams.update_one({"_id": data["team_id"]}, {"$set": {"rent_expiry": new_expiry}})
    chan = interaction.guild.get_channel(team["channel_id"])
    if chan:
        for mid in team["members"]:
            mem = interaction.guild.get_member(mid)
            if mem: await chan.set_permissions(mem, read_messages=True, send_messages=True)
        await chan.send(f"✅ **Rent Paid!** Chat unlocked.\nExpires: <t:{int(new_expiry.timestamp())}:R>")
    await interaction.response.send_message(f"✅ Paid {TEAM_CHANNEL_RENT} coins.")

# =========================================
# 💰 UTILS (INVITES, COINS, ADMIN)
# =========================================

class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green, custom_id="tic_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ow = {interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True), interaction.guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True)}
        for aid in ADMIN_IDS:
            m = interaction.guild.get_member(aid)
            if m: ow[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        c = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name}", overwrites=ow, topic=f"Ticket Owner: {interaction.user.id}")
        await c.send(f"{interaction.user.mention} Support will be with you shortly. Use `/close` to close.", view=None)
        await interaction.response.send_message(f"✅ Created: {c.mention}", ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Admin: Send ticket panel")
async def ticketpanel(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.send("📩 **Need Help?** Click below.", view=TicketView())
    await interaction.response.send_message("✅ Panel Sent", ephemeral=True)

@bot.tree.command(name="close", description="Close current ticket")
async def close(interaction: discord.Interaction):
    if "ticket-" not in interaction.channel.name: return await interaction.response.send_message("❌ This command only works in Ticket channels.", ephemeral=True)
    await interaction.response.send_message("👋 Closing in 5 seconds...")
    await asyncio.sleep(5)
    await interaction.channel.delete()

class JoinTeamView(discord.ui.View):
    def __init__(self, host_id):
        super().__init__(timeout=1800)
        self.host_id = host_id
    @discord.ui.button(label="✋ Request to Join", style=discord.ButtonStyle.green)
    async def request_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.host_id: return await interaction.response.send_message("❌ Host.", ephemeral=True)
        await interaction.response.send_message("✅ Sent!", ephemeral=True)
        host = interaction.guild.get_member(self.host_id)
        if host:
            try:
                view = AcceptTeamRequestView(interaction.user.id, interaction.guild)
                await host.send(f"📩 **{interaction.user.name}** wants to join your team!", view=view)
            except: await interaction.channel.send(f"{host.mention}, **{interaction.user.name}** wants to join!")

class AcceptTeamRequestView(discord.ui.View):
    def __init__(self, applicant_id, guild):
        super().__init__(timeout=300)
        self.applicant_id = applicant_id
        self.guild = guild
    @discord.ui.button(label="✅ Accept (Create Room)", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        applicant = self.guild.get_member(self.applicant_id)
        if not applicant: return
        cat = self.guild.get_channel(CAT_PRIVATE_ROOMS)
        overwrites = {self.guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True), applicant: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        chan = await self.guild.create_text_channel(f"team-{interaction.user.name[:5]}-{applicant.name[:5]}", category=cat, overwrites=overwrites)
        await interaction.response.send_message(f"✅ Created: {chan.name}")
        await chan.send(f"👋 **Team Up!**\n{interaction.user.mention} 🤝 {applicant.mention}")
        self.stop()
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.red)
    async def deny(self, interaction, button): await interaction.response.send_message("🚫 Denied.", ephemeral=True); self.stop()

@bot.tree.command(name="findteam", description="Find a team")
async def findteam(interaction: discord.Interaction, role: str, level: str):
    if interaction.channel.id != CH_FIND_TEAM: return await interaction.response.send_message(f"❌ Use <#{CH_FIND_TEAM}>", ephemeral=True)
    embed = discord.Embed(title="🎮 Looking for Team", color=discord.Color.orange())
    embed.add_field(name="Player", value=interaction.user.mention, inline=True)
    embed.add_field(name="Role", value=role, inline=True)
    embed.add_field(name="Level", value=level, inline=True)
    embed.set_footer(text="Click to request join")
    msg = await interaction.channel.send(embed=embed, view=JoinTeamView(interaction.user.id))
    await interaction.response.send_message("✅ Posted.", ephemeral=True)
    # Store for cleanup
    col_requests.insert_one({"message_id": msg.id, "channel_id": msg.channel.id, "expires_at": datetime.now(timezone.utc) + timedelta(days=1), "host_id": interaction.user.id, "price": 0})

@bot.event
async def on_message(message):
    if message.author.bot: return
    # STRICT CHANNEL CLEANER
    if not is_admin(message.author.id):
        if message.channel.id == CH_FIND_TEAM:
            await message.delete()
            msg = await message.channel.send(f"{message.author.mention} ❌ Only use `/findteam` here!")
            await asyncio.sleep(5)
            await msg.delete()
            return
        if message.channel.id == CH_FF_BET:
            await message.delete()
            msg = await message.channel.send(f"{message.author.mention} ❌ Only use `/challenge` here!")
            await asyncio.sleep(5)
            await msg.delete()
            return
        if message.channel.id == CH_WEEKLY_LB:
            await message.delete()
            msg = await message.channel.send(f"{message.author.mention} ❌ Only use `/leaderboard` here!")
            await asyncio.sleep(5)
            await msg.delete()
            return

    # Vouch
    pending = col_vouch.find_one({"channel_id": message.channel.id, "user_id": message.author.id})
    if pending:
        if re.match(r"^\[.+\]\s+i got\s+.+,\s*thanks\s+(@admin|<@!?\d+>|<@&\d+>)$", message.content, re.IGNORECASE):
            await message.add_reaction("✅")
            col_vouch.delete_one({"_id": pending["_id"]})
            if bot.get_channel(CH_VOUCH_LOG): await bot.get_channel(CH_VOUCH_LOG).send(f"✅ {message.author.name} vouched for `{pending['service']}`")
            await asyncio.sleep(5)
            await message.channel.delete()
        else:
            await message.delete()
            await message.channel.send("❌ Format: `[CODE] I got SERVICE, thanks @admin`", delete_after=5)

    # Match game confirmation
    match = col_matches.find_one({"channel_id": message.channel.id})
    if match and match.get("status") == "pending_game_name" and "free fire" in message.content.lower():
        col_matches.update_one({"_id": match["_id"]}, {"$set": {"status": "playing"}})
        await message.channel.send("✅ Match Started!")

    await bot.process_commands(message)

bot.run(TOKEN)
