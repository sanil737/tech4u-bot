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
CH_MATCH_RESULTS = 1467146334862835966 # 📢 Public Results
CH_HELPER_LOG = 1467388385508462739    # 🔐 Secret Helper Log
CH_FF_BET = 1467146811872641066
CH_MVP_HIGHLIGHTS = 1467148516718809149
CH_WEEKLY_LB = 1467148265597305046
CH_FULL_MAP_RESULTS = 1293634663461421140
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
    "coin_shield": {"price": 180, "name": "🛡️ Coin Shield", "desc": "Protect coins from risky matches"}
}

# Pricing
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
        self.check_invite_validation.start()
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
        print(f"⚠️ Error: {error_msg}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"⚠️ Error: {error_msg}", ephemeral=True)

    # 🔄 TASKS (Simplified)
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
        top_teams = list(col_teams.aggregate([{"$lookup": {"from": "users", "localField": "members", "foreignField": "_id", "as": "member_data"}}, {"$addFields": {"total_weekly_wins": {"$sum": "$member_data.weekly_wins"}}}, {"$sort": {"total_weekly_wins": -1}}, {"$limit": 5}]))
        embed = discord.Embed(title="🏆 WEEKLY LEADERBOARD RESULTS", description="Rewards distributed! Stats reset.", color=discord.Color.gold())
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
            if reward > 0:
                col_users.update_many({"_id": {"$in": t["members"]}}, {"$inc": {"coins": reward}})
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
        data = {"_id": user_id, "coins": 0, "daily_cd": None, "last_redeem": None, "current_private_channel_id": None, "invite_count": 0, "boosts": {}, "team_id": None, "wins": 0, "losses": 0, "weekly_wins": 0, "streak": 0, "mvp_count": 0}
        col_users.insert_one(data)
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
        content = (f"🔒 **Private Channel**\n👑 **Owner:** <@{owner_id}>\n👥 **Joined:** {joined_str}\n⏰ **Expires:** <t:{timestamp}:R>\n\n➕ **Upgrades:**\n`/adduser @user` (100 coins)\n`/addtime hours` (100 coins/hr)")
        await msg.edit(content=content)
    except: pass

# =========================================
# 👑 ADMIN & HELPER COMMANDS
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

# =========================================
# 🏆 ADVANCED WINNER & CONSENT SYSTEM
# =========================================

class ScoreConsentView(discord.ui.View):
    def __init__(self, team_a_id, team_b_id, winner_id, score, match_id, helper_id):
        super().__init__(timeout=180) # 3 mins to vote
        self.team_a = team_a_id
        self.team_b = team_b_id
        self.winner_id = winner_id
        self.score = score
        self.match_id = match_id
        self.helper_id = helper_id
        self.votes = {}

    async def finalize(self, interaction, show_score):
        # Disable buttons
        for child in self.children: child.disabled = True
        await interaction.message.edit(view=self)
        
        # Post Public Result
        res_chan = interaction.guild.get_channel(CH_MATCH_RESULTS)
        matchup = f"<@{self.team_a}> vs <@{self.team_b}>"
        winner = f"<@{self.winner_id}>"
        
        if res_chan:
            embed = discord.Embed(title="🏁 MATCH RESULT", color=discord.Color.green())
            embed.add_field(name="🎮 Game ID", value=self.match_id, inline=True)
            embed.add_field(name="⚔️ Matchup", value=matchup, inline=False)
            embed.add_field(name="🏆 Winner", value=winner, inline=True)
            
            if show_score:
                embed.add_field(name="📊 Score", value=f"**{self.score}**", inline=True)
                embed.set_footer(text="GG WP! 🔥")
            else:
                embed.set_footer(text="GG WP! (Score Hidden)")
                
            await res_chan.send(embed=embed)
        
        await interaction.channel.send("✅ **Result Posted!** Room deleting in 10 mins...")
        
        # Auto-Delete Room
        await asyncio.sleep(600)
        await interaction.channel.delete()

    @discord.ui.button(label="✅ YES (Show Score)", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.team_a, self.team_b]: return
        self.votes[interaction.user.id] = True
        await interaction.response.send_message(f"✅ Voted YES", ephemeral=True)
        
        # If both voted YES
        if self.votes.get(self.team_a) and self.votes.get(self.team_b):
            await self.finalize(interaction, True)

    @discord.ui.button(label="❌ NO (Hide Score)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.team_a, self.team_b]: return
        await interaction.response.send_message(f"🚫 Voted NO", ephemeral=True)
        await self.finalize(interaction, False)

@bot.tree.command(name="winner", description="Submit Match Result")
async def winner(interaction: discord.Interaction, gameid: str, winner: discord.Member, score: str):
    if not is_helper(interaction): return await interaction.response.send_message("❌ Admin/Helper only.", ephemeral=True)
    
    match = col_matches.find_one({"round_id": gameid})
    if not match: return await interaction.response.send_message(f"❌ Match ID `{gameid}` not found.", ephemeral=True)
    
    # 1. SECRET LOG
    log_chan = bot.get_channel(CH_HELPER_LOG)
    if log_chan:
        await log_chan.send(f"🔐 **Helper Log**\n🆔 Room: {gameid}\n🧑 Helper: {interaction.user.mention}\n💰 Reward: +10 Coins\n📌 Result Submitted.")
    
    # Give Reward
    if interaction.user.id not in ADMIN_IDS:
        col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": HELPER_REWARD}})

    # 2. UPDATE STATS
    col_users.update_one({"_id": winner.id}, {"$inc": {"wins": 1, "weekly_wins": 1}})
    pot = match["entry"] * 2
    prize = int(pot * (1 - SYSTEM_FEE))
    
    win_data = get_user_data(winner.id)
    if win_data['boosts'].get('double_coins'):
        prize *= 2
        col_users.update_one({"_id": winner.id}, {"$unset": {"boosts.double_coins": ""}})
    col_users.update_one({"_id": winner.id}, {"$inc": {"coins": prize}})
    
    loser_id = match['team_b'][0] if match['team_a'][0] == winner.id else match['team_a'][0]
    lose_data = get_user_data(loser_id)
    if lose_data['boosts'].get('entry_refund'):
        col_users.update_one({"_id": loser_id}, {"$inc": {"coins": int(match['entry'] * 0.5)}, "$unset": {"boosts.entry_refund": ""}})
    if not lose_data['boosts'].get('streak_protection'):
        col_users.update_one({"_id": loser_id}, {"$inc": {"losses": 1}, "$set": {"streak": 0}})
    else: col_users.update_one({"_id": loser_id}, {"$unset": {"boosts.streak_protection": ""}})

    try: await winner.send(f"🎉 You won Game `{gameid}`! +{prize} Coins.")
    except: pass
    
    col_matches.delete_one({"_id": match["_id"]})

    # 3. CONSENT MENU
    await interaction.response.send_message(f"🏁 **Match Ended!**\n🏆 Winner: {winner.mention}\n⏳ Waiting for score consent...", ephemeral=True)
    
    # Send Consent View to Channel
    view = ScoreConsentView(match['team_a'][0], match['team_b'][0], winner.id, score, gameid, interaction.user.id)
    await interaction.channel.send(f"📊 **Score Visibility Request**\n<@{match['team_a'][0]}> & <@{match['team_b'][0]}>\nDo you both agree to show the score **{score}** publicly?", view=view)

# =========================================
# 🔐 PRIVATE CHANNEL
# =========================================

class RequestView(discord.ui.View):
    def __init__(self, request_id, guest_ids):
        super().__init__(timeout=None)
        self.request_id = request_id
        self.guest_ids = guest_ids

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        req = col_requests.find_one({"_id": self.request_id})
        if not req: return await interaction.response.send_message("❌ Expired.", ephemeral=True)
        if interaction.user.id not in self.guest_ids: return await interaction.response.send_message("❌ Not invited.", ephemeral=True)

        await interaction.response.defer()
        col_requests.delete_one({"_id": self.request_id})
        
        guild = interaction.guild
        category = guild.get_channel(CAT_PRIVATE_ROOMS)
        host = guild.get_member(req["host_id"])
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
            host: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True)
        }

        try:
            if req["type"] == "text":
                chan = await guild.create_text_channel(req["name"], category=category, overwrites=overwrites)
            else:
                chan = await guild.create_voice_channel(req["name"], category=category, overwrites=overwrites)
            
            end_time = datetime.now(timezone.utc) + timedelta(hours=req['hours'])
            timestamp = int(end_time.timestamp())

            col_users.update_one({"_id": req["host_id"]}, {"$set": {"current_private_channel_id": chan.id}})
            col_channels.insert_one({"channel_id": chan.id, "owner_id": req["host_id"], "type": req["type"], "end_time": end_time})

            try: await interaction.message.edit(content=f"✅ **Created!** {chan.mention}\nAccepted by: {interaction.user.mention}", view=None, embed=None)
            except: pass
            
            main_msg_content = (
                f"🔒 **Private Channel**\n👑 **Owner:** {host.mention}\n👥 **Joined:** {host.mention}, {interaction.user.mention}\n"
                f"📛 **Room:** {chan.name}\n⏰ **Expires:** <t:{timestamp}:R>\n\n"
                f"➕ **Upgrades:**\n`/adduser @user` (100 coins)\n`/addtime hours` (100 coins/hr)"
            )
            main_msg = await chan.send(main_msg_content)
            col_channels.update_one({"channel_id": chan.id}, {"$set": {"main_msg_id": main_msg.id}})

        except Exception as e: await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.guest_ids: return await interaction.response.send_message("❌ Not invited.", ephemeral=True)
        self.guest_ids.remove(interaction.user.id)
        await interaction.response.send_message("🚫 Declined.", ephemeral=True)

@bot.tree.command(name="makeprivatechannel", description="Request private channel")
@app_commands.choices(channel_type=[app_commands.Choice(name="Text", value="text"), app_commands.Choice(name="Voice", value="voice")], duration=[app_commands.Choice(name="1 Hour", value=1), app_commands.Choice(name="2 Hours", value=2), app_commands.Choice(name="4 Hours", value=4)])
@app_commands.describe(members="Mention users (Required)")
async def makeprivate(interaction: discord.Interaction, channel_type: str, name: str, duration: int, members: str):
    await interaction.response.defer(ephemeral=False)
    try:
        config = col_settings.find_one({"_id": "config"})
        if config["panic"] and not is_admin(interaction.user.id): return await interaction.followup.send("🔒 Maintenance.")

        uid = interaction.user.id
        data = get_user_data(uid)
        if data.get("current_private_channel_id") and not is_admin(uid): return await interaction.followup.send("❌ You already have a channel.")

        guests = [int(id) for id in re.findall(r'<@!?(\d+)>', members)]
        guests = list(set(guests))
        if uid in guests: guests.remove(uid)
        
        if not guests: return await interaction.followup.send("❌ Mention at least 1 guest.")
        total = len(guests) + 1
        if total > 7: return await interaction.followup.send("❌ Max 7 users.")

        try: price = PRICES[channel_type][total][duration]
        except KeyError: return await interaction.followup.send("❌ Pricing Error.")

        if data["coins"] < price: return await interaction.followup.send(f"❌ Need {price} coins.")

        col_users.update_one({"_id": uid}, {"$inc": {"coins": -price}})
        req_id = ObjectId()
        
        embed = discord.Embed(title=f"🔒 {channel_type.title()} Room Request", description=f"{interaction.user.mention} wants a room.\n**Guests:** {' '.join([f'<@{g}>' for g in guests])}\n**Price:** {price}\n**Duration:** {duration}h", color=discord.Color.gold())
        msg = await interaction.followup.send(embed=embed, view=RequestView(req_id, guests))
        col_requests.insert_one({"_id": req_id, "host_id": uid, "guests": guests, "type": channel_type, "name": name, "price": price, "hours": duration, "end_time": datetime.now(timezone.utc) + timedelta(hours=duration), "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5), "msg_id": msg.id, "msg_channel_id": interaction.channel.id})
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected Error: {e}")

# =========================================
# 🛡️ TEAM SYSTEM
# =========================================

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
    if chan:
        await chan.set_permissions(user, overwrite=None)
        await chan.send(f"👋 {user.mention} removed from team.")
    await interaction.response.send_message(f"✅ Removed {user.name}.", ephemeral=True)

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
        "channel_id": chan.id, "rent_expiry": rent_expiry, "join_requests": []
    })
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
# 💰 UTILS & ADMIN COMMANDS (Daily, Pay, etc)
# =========================================

@bot.tree.command(name="daily", description="Claim 50 coins (24h)")
async def daily(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = interaction.user.id
    d = get_user_data(uid)
    now = datetime.now(timezone.utc)
    # Check cooldown for EVERYONE (Admin included)
    if d.get("daily_cd"):
        daily_cd = d["daily_cd"].replace(tzinfo=timezone.utc) if d["daily_cd"].tzinfo is None else d["daily_cd"]
        if now < daily_cd: return await interaction.followup.send(f"⏳ Come back in {int((daily_cd - now).total_seconds()//3600)}h.")
    col_users.update_one({"_id": uid}, {"$inc": {"coins": 50}, "$set": {"daily_cd": now + timedelta(hours=24)}})
    await interaction.followup.send(f"💰 +50 Coins!")

@bot.tree.command(name="pay", description="Pay coins")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    if amount <= 0: return await interaction.response.send_message("❌ Invalid.", ephemeral=True)
    s = get_user_data(interaction.user.id)
    if s["coins"] < amount: return await interaction.response.send_message("❌ Low balance.", ephemeral=True)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -amount}})
    col_users.update_one({"_id": user.id}, {"$inc": {"coins": amount}})
    await interaction.response.send_message(f"💸 Paid {amount} to {user.mention}")

# ... (Include other commands: addcoins, removecoins, lock, unlock, ann, clear, panic, profile, status, makeprivatechannel, adduser, addtime, prices, createteam, jointeam, acceptjoin, payteamrent, registerteam, createtournament, submitresults, boostshop, buy_boost) ...
# I'm truncating repeated commands to fit, assuming you paste them from the previous verified block.
# Ensure 'daily' above replaces previous version.
# Ensure 'findteam' and 'challenge' above include the channel check.

# =========================================
# 🚫 CHANNEL CLEANER (ON MESSAGE)
# =========================================

@bot.event
async def on_message(message):
    if message.author.bot: return
    
    # 🔎 Find Team Channel Logic
    if message.channel.id == CH_FIND_TEAM:
        await message.delete()
        msg = await message.channel.send(f"{message.author.mention} ❌ Only use `/findteam` here!")
        await asyncio.sleep(5)
        await msg.delete()
        return

    # 💰 Free Fire Bet Channel Logic
    if message.channel.id == CH_FF_BET:
        await message.delete()
        msg = await message.channel.send(f"{message.author.mention} ❌ Only use `/challenge` here!")
        await asyncio.sleep(5)
        await msg.delete()
        return

    # 📊 Weekly Leaderboard Logic
    if message.channel.id == CH_WEEKLY_LB:
        await message.delete()
        msg = await message.channel.send(f"{message.author.mention} ❌ Only use `/leaderboard` here!")
        await asyncio.sleep(5)
        await msg.delete()
        return
    
    # Game Confirmation Logic
    match = col_matches.find_one({"channel_id": message.channel.id})
    if match and match.get("status") == "pending_game_name" and "free fire" in message.content.lower():
        col_matches.update_one({"_id": match["_id"]}, {"$set": {"status": "playing"}})
        await message.channel.send("✅ Match Started!")

    await bot.process_commands(message)

# ... (Paste the rest of the commands from previous response here if missing) ...

bot.run(TOKEN)
