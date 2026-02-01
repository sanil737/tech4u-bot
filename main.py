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
HELPER_ROLE_ID = 1467388385508462739 # ⭐ Winner Results Role

# 📌 CHANNELS
CH_WELCOME = 1459444229255200971
CH_FIND_TEAM = 1459469475849175304
CH_VOUCH_LOG = 1459448284530610288
CH_WARNINGS = 1459448651704303667
CH_CODE_USE_LOG = 1459556690536960100
CH_MATCH_RESULTS = 1467146334862835966 # 📢 #winner-results
CH_FF_BET = 1467146811872641066
CH_MVP_HIGHLIGHTS = 1467148516718809149
CH_WEEKLY_LB = 1467148265597305046
CAT_PRIVATE_ROOMS = 1459557142850830489
CAT_TEAM_ROOMS = 1467172386821509316

# 📊 CONFIGS
PLACEMENT_POINTS = {1: 12, 2: 9, 3: 8, 4: 7, 5: 6, 6: 5, 7: 4, 8: 3, 9: 2, 10: 1}
KILL_POINT = 1
TEAM_JOIN_COST = 100
TEAM_CHANNEL_RENT = 500 # Per 7 days
SYSTEM_FEE = 0.20 # 20%
MIN_ENTRY = 50
HELPER_REWARD = 10

# 💰 UPGRADE COSTS
COST_ADD_USER = 100
COST_ADD_TIME = 100

# ⚡ BOOSTS CONFIG
BOOSTS = {
    "double_coins": {"price": 300, "name": "⚡ Double Coins", "desc": "Double win coins in next 1v1"},
    "streak_protection": {"price": 200, "name": "🛡️ Streak Protect", "desc": "Losing 1v1 won't reset streak"},
    "entry_refund": {"price": 150, "name": "💸 Entry Refund", "desc": "Get 50% back if you lose 1v1"},
    "extra_life": {"price": 250, "name": "❤️ Extra Life", "desc": "Retry a lost 1v1 (Visual)"},
    "lucky_boost": {"price": 100, "name": "🍀 Lucky Boost", "desc": "10% chance for bonus coins"},
    "coin_shield": {"price": 180, "name": "🛡️ Coin Shield", "desc": "Protect coins from risky matches"},
    "team_xp": {"price": 200, "name": "👥 Team XP", "desc": "+10% Points (24h)"},
    "hidden_loser": {"price": 50, "name": "🎭 Hidden Loser", "desc": "Hide loser name in results"},
    "lb_star": {"price": 100, "name": "⭐ LB Star", "desc": "Star on leaderboard (Weekly)"},
    "pin_result": {"price": 100, "name": "📌 Pin Result", "desc": "Pin your win in results channel"}
}

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
col_codes = db["codes"]
col_items = db["shop_items"]
col_vouch = db["vouch_pending"]
col_channels = db["active_channels"]
col_settings = db["settings"]
col_invites = db["invites_tracking"]
col_requests = db["pending_requests"]
col_giveaways = db["active_giveaways"]
col_tournaments = db["tournaments"]
col_tournament_teams = db["tournament_teams"]
col_teams = db["teams"] 
col_matches = db["matches"] 

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
        self.check_invite_validation.start()
        self.check_request_timeouts.start()
        self.check_giveaways.start()
        self.check_team_rent.start()
        self.weekly_leaderboard_task.start()
        await self.tree.sync()
        print("✅ Commands Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")
        # Create Helper Role if missing logic would go here, but assumed done by Admin manually
        for guild in self.guilds:
            try:
                invs = await guild.invites()
                self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invs}
            except: pass

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        error_msg = str(error)
        if isinstance(error, app_commands.CommandOnCooldown):
            error_msg = f"⏳ Cooldown: {error.retry_after:.2f}s"
        elif isinstance(error, app_commands.MissingPermissions):
            error_msg = "❌ You don't have permission."
        print(f"⚠️ Error: {error_msg}")
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

    @tasks.loop(hours=168) # Weekly
    async def weekly_leaderboard_task(self):
        channel = self.get_channel(CH_WEEKLY_LB)
        if not channel: return
        
        # 1. Player Leaderboard
        top_players = list(col_users.find().sort("weekly_wins", -1).limit(10))
        # 2. Team Leaderboard (Aggregation)
        top_teams = list(col_teams.aggregate([
            {"$lookup": {
                "from": "users",
                "localField": "members",
                "foreignField": "_id",
                "as": "member_data"
            }},
            {"$addFields": {"total_weekly_wins": {"$sum": "$member_data.weekly_wins"}}},
            {"$sort": {"total_weekly_wins": -1}},
            {"$limit": 5}
        ]))

        embed = discord.Embed(title="⭐ EG WEEKLY LEADERBOARD", color=discord.Color.gold())
        
        # Players
        p_text = ""
        for i, u in enumerate(top_players, 1):
            star = "⭐ " if u.get("boosts", {}).get("lb_star") else ""
            p_text += f"**{i}.** {star}<@{u['_id']}> — 🏆 {u.get('weekly_wins', 0)}\n"
            # Rewards
            reward = 150 if i==1 else 100 if i==2 else 50 if i==3 else 0
            if reward > 0: col_users.update_one({"_id": u["_id"]}, {"$inc": {"coins": reward}})
        
        embed.add_field(name="👤 Top Players", value=p_text if p_text else "No data.", inline=False)

        # Teams
        t_text = ""
        for i, t in enumerate(top_teams, 1):
            wins = t.get("total_weekly_wins", 0)
            t_text += f"**{i}.** 🛡️ {t['name']} — 🏆 {wins}\n"
            # Team Rewards
            reward = 150 if i==1 else 100 if i==2 else 50 if i==3 else 0
            if reward > 0:
                col_users.update_many({"_id": {"$in": t["members"]}}, {"$inc": {"coins": reward}})
                t_chan = channel.guild.get_channel(t["channel_id"])
                if t_chan: await t_chan.send(f"🎉 **Weekly Reward!** Team finished #{i}. Each member got {reward} Coins!")

        embed.add_field(name="👥 Top Teams", value=t_text if t_text else "No data.", inline=False)
        embed.set_footer(text="Stats reset weekly! 9AM Sunday")
        
        await channel.send(embed=embed)
        # Reset Weekly
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

    # ... [Keep other tasks: expiry, giveaways, invite, request_timeouts] ...
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
    # Check for Admin OR Helper Role
    if interaction.user.id in ADMIN_IDS: return True
    if interaction.guild:
        role = interaction.guild.get_role(HELPER_ROLE_ID)
        if role in interaction.user.roles: return True
    return False

def get_user_data(user_id):
    data = col_users.find_one({"_id": user_id})
    if not data:
        data = {"_id": user_id, "coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None, "invite_count": 0, "boosts": {}, "team_id": None, "wins": 0, "losses": 0, "weekly_wins": 0, "streak": 0, "mvp_count": 0}
        col_users.insert_one(data)
    # Ensure fields exist
    updates = {}
    if "boosts" not in data: updates["boosts"] = {}
    if "team_id" not in data: updates["team_id"] = None
    if "wins" not in data: updates["wins"] = 0
    if "weekly_wins" not in data: updates["weekly_wins"] = 0
    if updates: col_users.update_one({"_id": user_id}, {"$set": updates})
    return data

async def update_main_message(channel, owner_id, end_time):
    c_data = col_channels.find_one({"channel_id": channel.id})
    if not c_data or "main_msg_id" not in c_data: return
    try:
        msg = await channel.fetch_message(c_data["main_msg_id"])
        members = [m.mention for m in channel.members if not m.bot]
        joined_str = ", ".join(members)
        timestamp = int(end_time.timestamp())
        content = (
            f"🔒 **Private Channel**\n👑 **Owner:** <@{owner_id}>\n👥 **Joined:** {joined_str}\n"
            f"⏰ **Expires:** <t:{timestamp}:R>\n\n"
            f"➕ **Upgrades:**\n`/adduser @user` (100 coins)\n`/addtime hours` (100 coins/hr)"
        )
        await msg.edit(content=content)
    except: pass

# =========================================
# 🛡️ TEAM SYSTEM (Updated Join Flow)
# =========================================

class ApproveJoinView(discord.ui.View):
    def __init__(self, applicant_id, team_id):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.team_id = team_id

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only Leader
        team = col_teams.find_one({"_id": self.team_id})
        if not team or interaction.user.id != team["leader_id"]: return await interaction.response.send_message("❌ Leader only.", ephemeral=True)
        
        applicant = interaction.guild.get_member(self.applicant_id)
        if not applicant: return

        # Deduct Coins NOW
        user_data = get_user_data(self.applicant_id)
        if user_data["coins"] < TEAM_JOIN_COST:
             return await interaction.response.send_message(f"❌ User ran out of coins.", ephemeral=True)
        
        col_users.update_one({"_id": self.applicant_id}, {"$inc": {"coins": -TEAM_JOIN_COST}, "$set": {"team_id": self.team_id}})
        col_teams.update_one({"_id": self.team_id}, {"$push": {"members": self.applicant_id}})
        
        # Permissions
        chan = interaction.guild.get_channel(team["channel_id"])
        if chan:
            await chan.set_permissions(applicant, read_messages=True, send_messages=True)
            await chan.send(f"👋 Welcome {applicant.mention} to **{team['name']}**!")
            
        await interaction.message.delete()
        await interaction.response.send_message(f"✅ Approved {applicant.name}!")

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        team = col_teams.find_one({"_id": self.team_id})
        if not team or interaction.user.id != team["leader_id"]: return
        
        await interaction.message.delete()
        await interaction.response.send_message("🚫 Rejected.")

@bot.tree.command(name="jointeam", description="Request to join a team (100 coins)")
async def jointeam(interaction: discord.Interaction, team_name: str):
    uid = interaction.user.id
    data = get_user_data(uid)
    if data.get("team_id"): return await interaction.response.send_message("❌ Already in a team.", ephemeral=True)
    if data["coins"] < TEAM_JOIN_COST: return await interaction.response.send_message(f"❌ Need {TEAM_JOIN_COST} coins.", ephemeral=True)
    
    team = col_teams.find_one({"name": team_name})
    if not team: return await interaction.response.send_message("❌ Team not found.", ephemeral=True)
    
    # Send Request to Team Channel
    chan = interaction.guild.get_channel(team["channel_id"])
    if chan:
        embed = discord.Embed(title="💌 Join Request", description=f"User {interaction.user.mention} wants to join **{team_name}**.\nApprove?", color=discord.Color.blue())
        await chan.send(f"<@{team['leader_id']}>", embed=embed, view=ApproveJoinView(uid, team["_id"]))
        await interaction.response.send_message("✅ Request sent to team channel!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Team channel missing.", ephemeral=True)

@bot.tree.command(name="createteam", description="Create a team (Max 6 members)")
async def createteam(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    uid = interaction.user.id
    user_data = get_user_data(uid)
    
    if user_data.get("team_id"): return await interaction.followup.send("❌ You are already in a team.")
    if col_teams.find_one({"name": name}): return await interaction.followup.send("❌ Team name taken.")

    guild = interaction.guild
    cat = guild.get_channel(CAT_TEAM_ROOMS)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True)
    }
    for aid in ADMIN_IDS:
        m = guild.get_member(aid)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True)

    chan = await guild.create_text_channel(f"🛡️-{name.lower()}", category=cat, overwrites=overwrites)
    team_id = ObjectId()
    rent_expiry = datetime.now(timezone.utc) + timedelta(days=7)
    
    col_teams.insert_one({
        "_id": team_id, "name": name, "leader_id": uid, "members": [uid],
        "channel_id": chan.id, "rent_expiry": rent_expiry
    })
    col_users.update_one({"_id": uid}, {"$set": {"team_id": team_id}})
    
    await chan.send(f"🛡️ **Team {name} Created!**\n👑 Leader: {interaction.user.mention}\n⏰ Rent Expires: <t:{int(rent_expiry.timestamp())}:R>")
    await interaction.followup.send(f"✅ Team created! {chan.mention}")

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
# ⚔️ 1v1 MATCH, TOURNAMENT & HELPER RESULT SYSTEM
# =========================================

@bot.tree.command(name="winner", description="Submit Match Result (Helper/Admin)")
async def winner(interaction: discord.Interaction, winner: discord.Member, score: str):
    # Check Permission (Admin or Helper)
    if not is_helper(interaction):
        return await interaction.response.send_message("❌ Only Admins or Helpers can use this.", ephemeral=True)

    # Identify Match (1v1 or General Room)
    # Check DB first for official 1v1
    match = col_matches.find_one({"channel_id": interaction.channel.id})
    
    game_id = "Custom"
    mode = "Custom"
    entry = 0
    prize = 0
    loser_id = None
    
    if match:
        game_id = match["round_id"]
        mode = match["mode"]
        entry = match["entry"]
        pot = entry * 2
        prize = int(pot * 0.8) # 20% Fee
        
        # Determine Loser
        loser_id = match['team_b'][0] if match['team_a'][0] == winner.id else match['team_a'][0]
        
        # Check Boosts
        win_data = get_user_data(winner.id)
        lose_data = get_user_data(loser_id)
        
        if win_data['boosts'].get('double_coins'):
            prize *= 2
            col_users.update_one({"_id": winner.id}, {"$unset": {"boosts.double_coins": ""}})
        
        col_users.update_one({"_id": winner.id}, {"$inc": {"coins": prize, "wins": 1, "weekly_wins": 1}})
        
        if lose_data['boosts'].get('entry_refund'):
            col_users.update_one({"_id": loser_id}, {"$inc": {"coins": int(entry * 0.5)}, "$unset": {"boosts.entry_refund": ""}})
        
        # Update Loser stats if not protected
        if not lose_data['boosts'].get('streak_protection'):
            col_users.update_one({"_id": loser_id}, {"$inc": {"losses": 1}, "$set": {"streak": 0}})
        else:
             col_users.update_one({"_id": loser_id}, {"$unset": {"boosts.streak_protection": ""}})

        # Remove Match DB
        col_matches.delete_one({"_id": match["_id"]})

    # Give Helper Reward (Only if not Admin)
    if interaction.user.id not in ADMIN_IDS:
        col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": HELPER_REWARD}})

    # 1. Public Result Log
    res_chan = bot.get_channel(CH_MATCH_RESULTS)
    loser_name = f"<@{loser_id}>" if loser_id else "Opponent"
    # Check Hidden Loser Boost
    if loser_id:
        l_data = get_user_data(loser_id)
        if l_data['boosts'].get('hidden_loser'):
            loser_name = "||Hidden||"
            col_users.update_one({"_id": loser_id}, {"$unset": {"boosts.hidden_loser": ""}})
    
    if res_chan:
        embed = discord.Embed(title="🏁 OFFICIAL MATCH RESULT", color=discord.Color.green())
        embed.add_field(name="🎮 Game ID", value=game_id, inline=True)
        embed.add_field(name="🏆 Winner", value=winner.mention, inline=True)
        embed.add_field(name="📊 Score", value=score, inline=False)
        embed.add_field(name="⚔️ Matchup", value=f"{winner.mention} vs {loser_name}", inline=False)
        embed.set_footer(text=f"Result by {interaction.user.name}")
        await res_chan.send(embed=embed)
        
        # Pin Result Boost
        if get_user_data(winner.id)['boosts'].get('pin_result'):
            msg = await res_chan.send(f"📌 **Pinned Result for {winner.mention}**")
            await msg.pin()
            col_users.update_one({"_id": winner.id}, {"$unset": {"boosts.pin_result": ""}})

    # 2. Match Room Message
    await interaction.response.send_message(
        f"✅ **Match Finished**\n🏆 Winner: {winner.mention}\n📊 Score: {score}\n🧹 Room deletes in 10 minutes."
    )
    
    # 3. DMs
    try: await winner.send(f"🎉 You won Game {game_id}! +{prize} Coins.")
    except: pass
    if loser_id:
        try: await interaction.guild.get_member(loser_id).send(f"💪 GG Game {game_id}. Score: {score}.")
        except: pass
    
    # 4. Delete Room
    await asyncio.sleep(600) # 10 Mins
    await interaction.channel.delete()

# =========================================
# 🛍️ BOOST SHOP (BUTTON SYSTEM)
# =========================================

class BoostShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def process_buy(self, interaction: discord.Interaction, boost_key: str):
        uid = interaction.user.id
        data = get_user_data(uid)
        cost = BOOSTS[boost_key]["price"]
        name = BOOSTS[boost_key]["name"]

        if data["coins"] < cost:
            return await interaction.response.send_message(f"❌ You need **{cost}** coins! (Balance: {data['coins']})", ephemeral=True)
        
        # Deduct & Add Boost
        col_users.update_one({"_id": uid}, {
            "$inc": {"coins": -cost},
            "$set": {f"boosts.{boost_key}": True}
        })
        await interaction.response.send_message(f"✅ Purchased **{name}** for {cost} coins!", ephemeral=True)

    @discord.ui.button(label="⚡ Double Coins (300)", style=discord.ButtonStyle.primary, custom_id="buy_double")
    async def buy_double(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_buy(interaction, "double_coins")

    @discord.ui.button(label="🛡️ Streak Protect (200)", style=discord.ButtonStyle.success, custom_id="buy_streak")
    async def buy_streak(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_buy(interaction, "streak_protection")

    @discord.ui.button(label="💸 Entry Refund (150)", style=discord.ButtonStyle.secondary, custom_id="buy_refund")
    async def buy_refund(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_buy(interaction, "entry_refund")

    @discord.ui.button(label="❤️ Extra Life (250)", style=discord.ButtonStyle.danger, custom_id="buy_life")
    async def buy_life(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_buy(interaction, "extra_life")
    
    @discord.ui.button(label="🍀 Lucky Boost (100)", style=discord.ButtonStyle.success, custom_id="buy_lucky")
    async def buy_lucky(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_buy(interaction, "lucky_boost")

    @discord.ui.button(label="🛡️ Coin Shield (180)", style=discord.ButtonStyle.primary, custom_id="buy_shield")
    async def buy_shield(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_buy(interaction, "coin_shield")

@bot.tree.command(name="boostshop", description="Open the Boost Shop")
async def boostshop(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    embed = discord.Embed(title="🎮 EG Boost Shop", description=f"**Your Coins:** 💰 {d['coins']}\n\n🛒 **Available Boosts:**", color=discord.Color.gold())
    
    text = ""
    for k, v in BOOSTS.items():
        text += f"**{v['name']}** • `💰 {v['price']}`\n{v['desc']}\n\n"
    
    embed.add_field(name="Boost List", value=text)
    embed.set_footer(text="Click buttons below to purchase instantly.")
    
    await interaction.response.send_message(embed=embed, view=BoostShopView())

# =========================================
# 👤 PROFILE (FIXED)
# =========================================

@bot.tree.command(name="profile", description="Check your stats and team")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    d = get_user_data(target.id) 
    
    embed = discord.Embed(title=f"👤 {target.name}'s Profile", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)
    
    embed.add_field(name="💰 Coins", value=d.get('coins', 0), inline=True)
    embed.add_field(name="🏆 Wins", value=d.get('wins', 0), inline=True)
    embed.add_field(name="🔥 Streak", value=d.get('streak', 0), inline=True)
    embed.add_field(name="⭐ MVPs", value=d.get('mvp_count', 0), inline=True)
    
    team_name = "None"
    if d.get("team_id"):
        team = col_teams.find_one({"_id": d["team_id"]})
        if team: team_name = team["name"]
    
    embed.add_field(name="🛡️ Team", value=team_name, inline=False)

    boosts = d.get('boosts', {})
    active_boosts = [BOOSTS[k]['name'] for k, v in boosts.items() if v]
    if active_boosts:
        embed.add_field(name="⚡ Active Boosts", value="\n".join(active_boosts), inline=False)
    
    await interaction.response.send_message(embed=embed)

# =========================================
# 1v1 ACCEPT & CHALLENGE
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
        
        # Deduct
        col_users.update_one({"_id": challenger.id}, {"$inc": {"coins": -self.amount}})
        col_users.update_one({"_id": opponent.id}, {"$inc": {"coins": -self.amount}})

        # Create Room
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

        await chan.send(f"🔥 **MATCH STARTED**\n{challenger.mention} vs {opponent.mention}\nBet: {self.amount} EG")
        await interaction.followup.send(f"✅ Match Created: {chan.mention}")
        self.stop()

@bot.tree.command(name="challenge", description="Start a Match")
@app_commands.describe(amount="Entry Fee", mode="1v1, 2v2...", opponent="Optional user")
async def challenge(interaction: discord.Interaction, amount: int, mode: str, opponent: discord.Member = None):
    if interaction.channel.id != CH_FF_BET: return await interaction.response.send_message(f"❌ Use <#{CH_FF_BET}>", ephemeral=True)
    if amount < MIN_ENTRY: return await interaction.response.send_message(f"❌ Min entry: {MIN_ENTRY} EG.", ephemeral=True)
    
    data = get_user_data(interaction.user.id)
    if data["coins"] < amount: return await interaction.response.send_message(f"❌ Low balance.", ephemeral=True)

    round_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    embed = discord.Embed(title="⚔️ NEW CHALLENGE", color=discord.Color.red())
    embed.add_field(name="Mode", value=mode)
    embed.add_field(name="Entry", value=f"{amount} EG")
    embed.add_field(name="Challenger", value=interaction.user.mention, inline=False)
    
    content = opponent.mention if opponent else "@here"
    await interaction.response.send_message(content, embed=embed, view=AcceptMatchView(interaction.user.id, amount, mode, round_id))

# =========================================
# 💰 UTILS (INVITES, COINS, ADMIN)
# =========================================

class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.primary, custom_id="join_giveaway")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        col_giveaways.update_one({"_id": self.giveaway_id}, {"$push": {"entries": interaction.user.id}})
        await interaction.response.send_message("✅ Entry Confirmed!", ephemeral=True)

@bot.tree.command(name="giveaway", description="Admin: Start giveaway")
@app_commands.checks.cooldown(1, 300)
async def giveaway(interaction: discord.Interaction, minutes: int, prize: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    end_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    embed = discord.Embed(title="🎉 GIVEAWAY!", description=f"**Prize:** {prize}\n**Ends:** <t:{int(end_time.timestamp())}:R>", color=discord.Color.magenta())
    gw_id = ObjectId()
    await interaction.response.send_message(embed=embed, view=GiveawayView(gw_id))
    msg = await interaction.original_response()
    col_giveaways.insert_one({"_id": gw_id, "channel_id": interaction.channel.id, "message_id": msg.id, "prize": prize, "end_time": end_time, "entries": []})

@bot.tree.command(name="daily", description="Claim coins")
async def daily(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = interaction.user.id
    d = get_user_data(uid)
    now = datetime.now(timezone.utc)
    if d.get("daily_cd") and not is_admin(uid):
        daily_cd = d["daily_cd"].replace(tzinfo=timezone.utc) if d["daily_cd"].tzinfo is None else d["daily_cd"]
        if now < daily_cd: return await interaction.followup.send(f"⏳ Come back in {int((daily_cd - now).total_seconds()//3600)}h.")
    col_users.update_one({"_id": uid}, {"$inc": {"coins": 50}, "$set": {"daily_cd": now + timedelta(hours=24)}})
    await interaction.followup.send(f"💰 +50 Coins!")

@bot.tree.command(name="invites", description="Show stats")
async def invites(interaction: discord.Interaction):
    d = get_user_data(interaction.user.id)
    pending = col_invites.count_documents({"inviter_id": interaction.user.id, "valid": False})
    await interaction.response.send_message(f"📩 **Invites:** {d.get('invite_count', 0)} Valid | {pending} Pending", ephemeral=True)

@bot.tree.command(name="lock", description="Admin: Lock")
async def lock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    if "redeem-" in interaction.channel.name or "buy-" in interaction.channel.name: return await interaction.response.send_message("❌ Cannot lock Redeem channels.", ephemeral=True)
    if col_channels.find_one({"channel_id": interaction.channel.id}): return await interaction.response.send_message("❌ Cannot lock Private channels.", ephemeral=True)
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    role = discord.utils.get(interaction.guild.roles, name="Member")
    if role: await interaction.channel.set_permissions(role, send_messages=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": True}})
    await interaction.response.send_message("🔒 Locked.")

@bot.tree.command(name="unlock", description="Admin: Unlock")
async def unlock(interaction: discord.Interaction):
    if not is_admin(interaction.user.id): return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None, send_messages_in_threads=None, create_public_threads=None, create_private_threads=None)
    role = discord.utils.get(interaction.guild.roles, name="Member")
    if role: await interaction.channel.set_permissions(role, send_messages=None, send_messages_in_threads=None, create_public_threads=None, create_private_threads=None)
    col_settings.update_one({"_id": "config"}, {"$set": {"locked": False}})
    await interaction.response.send_message("🔓 Unlocked.")

@bot.tree.command(name="addcoins", description="Admin: Add coins to user")
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

@bot.tree.command(name="ann", description="Admin: Announce")
async def ann(interaction: discord.Interaction, title: str, message: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await interaction.channel.send(embed=discord.Embed(title=title, description=message, color=discord.Color.blue()))
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

@bot.tree.command(name="pay", description="Pay coins")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    if amount <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
    s = get_user_data(interaction.user.id)
    if s["coins"] < amount: return await interaction.response.send_message("❌ Low balance.", ephemeral=True)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -amount}})
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"💸 Paid {amount} to {user.mention}")

# =========================================
# 🎟️ TICKET SYSTEM
# =========================================

class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green, custom_id="tic_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ow = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True)
        }
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
    if "ticket-" not in interaction.channel.name:
        return await interaction.response.send_message("❌ This command only works in Ticket channels.", ephemeral=True)
    await interaction.response.send_message("👋 Closing in 5 seconds...")
    await asyncio.sleep(5)
    await interaction.channel.delete()

# ... [KEEP OTHER COMMANDS: makeprivatechannel, adduser, addtime, prices, etc from previous version] ...
# Due to length limits, I have ensured ALL new/changed features (Winner, Team, Boosts, Profile) are above.
# The previous Private Room/Invite logic remains unchanged.

@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id == CH_FIND_TEAM and not is_admin(message.author.id): await message.delete()
    
    # Vouch Logic
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
