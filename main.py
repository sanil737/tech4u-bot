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

# 📌 CHANNELS
CH_WELCOME = 1459444229255200971
CH_FIND_TEAM = 1459469475849175304
CH_VOUCH_LOG = 1459448284530610288
CH_WARNINGS = 1459448651704303667
CH_FULL_MAP_RESULTS = 1293634663461421140 
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

# 💰 UPGRADE COSTS
COST_ADD_USER = 100
COST_ADD_TIME = 100

# ⚡ BOOSTS CONFIG
BOOSTS = {
    "double_coins": {"price": 300, "desc": "Double win coins in next 1v1"},
    "streak_protection": {"price": 200, "desc": "Losing 1v1 won't reset streak"},
    "entry_refund": {"price": 150, "desc": "Get 50% back if you lose 1v1"},
    "extra_life": {"price": 250, "desc": "Retry without losing coins (Visual)"},
    "lucky_boost": {"price": 100, "desc": "10% chance to earn bonus coins"},
    "coin_shield": {"price": 180, "desc": "Protect coins in risky matches"}
}

# Pricing for Private Rooms
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
        self.check_channel_expiry.start()
        self.check_request_timeouts.start()
        self.check_team_rent.start()
        self.weekly_leaderboard_task.start()
        await self.tree.sync()
        print("✅ Commands Synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user}")

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

    @tasks.loop(hours=168)
    async def weekly_leaderboard_task(self):
        channel = self.get_channel(CH_WEEKLY_LB)
        if not channel: return
        top_users = col_users.find().sort("weekly_wins", -1).limit(10)
        embed = discord.Embed(title="📊 WEEKLY LEADERBOARD", color=discord.Color.gold())
        text = ""
        for i, u in enumerate(top_users, 1): text += f"**{i}.** <@{u['_id']}> — 🏆 {u.get('weekly_wins', 0)} Wins\n"
        embed.description = text if text else "No matches yet."
        await channel.send(embed=embed)
        col_users.update_many({}, {"$set": {"weekly_wins": 0}})

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
# 🛡️ TEAM SYSTEM
# =========================================

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
    if uid in team.get("join_requests", []): return await interaction.response.send_message("❌ Request sent.", ephemeral=True)

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
    
    # 🔥 STACK TIME LOGIC
    team = col_teams.find_one({"_id": data["team_id"]})
    current_expiry = team.get("rent_expiry")
    
    # If expired or None, start from now. If active, add to existing time.
    now = datetime.now(timezone.utc)
    if current_expiry and current_expiry.tzinfo is None: current_expiry = current_expiry.replace(tzinfo=timezone.utc)

    if not current_expiry or current_expiry < now:
        new_expiry = now + timedelta(days=7)
    else:
        new_expiry = current_expiry + timedelta(days=7)

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
# ⚔️ TOURNAMENTS & MATCHES
# =========================================

@bot.tree.command(name="createtournament", description="Admin: Create tournament")
async def createtournament(interaction: discord.Interaction, name: str, time: str, slots: int, total_prize: int):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    tid = f"T-{random.randint(1000, 9999)}"
    p1, p2, p3 = int(total_prize * 0.50), int(total_prize * 0.30), int(total_prize * 0.20)
    
    embed = discord.Embed(title="🔥 NEW TOURNAMENT 🔥", description=f"**{name}**", color=discord.Color.red())
    embed.add_field(name="🆔 ID", value=f"`{tid}`")
    embed.add_field(name="💰 Prize", value=f"{total_prize} EG")
    embed.add_field(name="🏆 Split", value=f"🥇 {p1} | 🥈 {p2} | 🥉 {p3}", inline=False)
    embed.add_field(name="📌 Join", value=f"`/registerteam {tid} [TeamName]`")
    
    col_tournaments.insert_one({"tid": tid, "name": name, "status": "open", "distribution": [p1, p2, p3], "created_at": datetime.now(timezone.utc)})
    await interaction.channel.send(content="@everyone", embed=embed)
    await interaction.response.send_message(f"✅ Tournament created!", ephemeral=True)

@bot.tree.command(name="registerteam", description="Register squad for tournament")
async def registerteam(interaction: discord.Interaction, tournament_id: str, team_name: str):
    tourney = col_tournaments.find_one({"tid": tournament_id})
    if not tourney or tourney["status"] != "open": return await interaction.response.send_message("❌ Invalid/Closed.", ephemeral=True)
    if col_tournament_teams.find_one({"tid": tournament_id, "leader_id": interaction.user.id}): return await interaction.response.send_message("❌ Already registered.", ephemeral=True)
    
    guild = interaction.guild
    cat = guild.get_channel(CAT_PRIVATE_ROOMS) # Use private room cat for IDP
    overwrites = {guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True)}
    for a in ADMIN_IDS:
        m = guild.get_member(a)
        if m: overwrites[m] = discord.PermissionOverwrite(read_messages=True)
    
    chan = await guild.create_text_channel(f"🔐-idp-{team_name[:5]}", category=cat, overwrites=overwrites)
    col_tournament_teams.insert_one({"tid": tournament_id, "team_name": team_name, "leader_id": interaction.user.id, "channel_id": chan.id})
    await chan.send(f"🔐 **IDP Created** for {team_name}\nLeader: {interaction.user.mention}")
    await interaction.response.send_message(f"✅ Registered! {chan.mention}", ephemeral=True)

@bot.tree.command(name="submitresults", description="Admin: Process results")
async def submitresults(interaction: discord.Interaction, tournament_id: str, data: str):
    if not is_admin(interaction.user.id): return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await interaction.response.defer()
    
    tourney = col_tournaments.find_one({"tid": tournament_id})
    if not tourney: return await interaction.followup.send("❌ Invalid ID.")
    
    raw_entries = re.split(r'[,\n]', data)
    results = []
    for entry in raw_entries:
        match = re.search(r'^(?P<name>.+?)\s+kill\s+(?P<kills>\d+)\s+placement\s+(?P<pos>\d+)', entry.strip(), re.IGNORECASE)
        if match:
            results.append({
                "name": match.group("name").strip(),
                "kills": int(match.group("kills")),
                "pos": int(match.group("pos")),
                "total": PLACEMENT_POINTS.get(int(match.group("pos")), 0) + (int(match.group("kills")) * KILL_POINT)
            })
    
    sorted_results = sorted(results, key=lambda x: (-x['total'], -x['kills'], x['pos']))
    prizes = tourney["distribution"]
    
    embed = discord.Embed(title=f"🏆 {tourney['name']} RESULTS", color=discord.Color.gold())
    desc = ""
    for i, res in enumerate(sorted_results):
        prize_txt = f" • **Won: {prizes[i]} EG**" if i < 3 else ""
        desc += f"**#{i+1} {res['name']}** - {res['total']} Pts{prize_txt}\n"
    
    embed.description = desc
    res_chan = bot.get_channel(CH_FULL_MAP_RESULTS)
    if res_chan: await res_chan.send(embed=embed)
    
    col_tournaments.update_one({"tid": tournament_id}, {"$set": {"status": "finished"}})
    await interaction.followup.send("✅ Results posted.")

# =========================================
# ⚔️ 1v1 MATCH & BOOSTS
# =========================================

class RematchView(discord.ui.View):
    def __init__(self, p1_id, p2_id, bet, mode):
        super().__init__(timeout=60)
        self.p1 = p1_id; self.p2 = p2_id; self.bet = bet; self.mode = mode; self.accepted = []
    
    @discord.ui.button(label="⚔️ Rematch?", style=discord.ButtonStyle.blurple)
    async def rematch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.p1, self.p2] or interaction.user.id in self.accepted: return
        d = get_user_data(interaction.user.id)
        if d["coins"] < self.bet: return await interaction.response.send_message("❌ Not enough coins!", ephemeral=True)
        self.accepted.append(interaction.user.id)
        await interaction.response.send_message("✅ Accepted!")
        if len(self.accepted) == 2:
            col_users.update_one({"_id": self.p1}, {"$inc": {"coins": -self.bet}})
            col_users.update_one({"_id": self.p2}, {"$inc": {"coins": -self.bet}})
            
            guild = interaction.guild
            cat = guild.get_channel(CAT_PRIVATE_ROOMS)
            chan = await guild.create_text_channel(f"rematch-{random.randint(100,999)}", category=cat)
            await chan.set_permissions(guild.get_member(self.p1), read_messages=True)
            await chan.set_permissions(guild.get_member(self.p2), read_messages=True)
            
            col_matches.insert_one({"channel_id": chan.id, "team_a": [self.p1], "team_b": [self.p2], "mode": self.mode, "entry": self.bet, "status": "playing"})
            await chan.send(f"🔥 **REMATCH STARTED!** Bet: {self.bet}")
            self.stop()

@bot.tree.command(name="winner", description="Declare winner")
async def winner(interaction: discord.Interaction, winner: discord.Member, score: str):
    if not is_admin(interaction.user.id): return
    match = col_matches.find_one({"channel_id": interaction.channel.id})
    if not match: return await interaction.response.send_message("❌ Not a match.", ephemeral=True)
    
    pot = match["entry"] * 2
    prize = int(pot * 0.8)
    
    win_data = get_user_data(winner.id)
    if win_data['boosts'].get('double_coins'):
        prize *= 2
        col_users.update_one({"_id": winner.id}, {"$unset": {"boosts.double_coins": ""}})
    
    col_users.update_one({"_id": winner.id}, {"$inc": {"coins": prize, "wins": 1}})
    
    await interaction.channel.send(f"🏆 **Winner:** {winner.mention} (+{prize} EG)\nScore: {score}", view=RematchView(match['team_a'][0], match['team_b'][0], match['entry'], match['mode']))
    col_matches.delete_one({"_id": match["_id"]})

@bot.tree.command(name="buy_boost", description="Buy gameplay boost")
@app_commands.choices(boost=[app_commands.Choice(name=f"{k.replace('_', ' ').title()} ({v['price']})", value=k) for k, v in BOOSTS.items()])
async def buy_boost(interaction: discord.Interaction, boost: str):
    data = get_user_data(interaction.user.id)
    cost = BOOSTS[boost]["price"]
    if data["coins"] < cost: return await interaction.response.send_message(f"❌ Need {cost} coins.", ephemeral=True)
    col_users.update_one({"_id": interaction.user.id}, {"$inc": {"coins": -cost}, "$set": {f"boosts.{boost}": True}})
    await interaction.response.send_message(f"✅ Purchased **{boost}**!", ephemeral=True)

# =========================================
# 🔎 FIND TEAM (YES/NO BUTTON SYSTEM)
# =========================================

class JoinTeamView(discord.ui.View):
    def __init__(self, host_id):
        super().__init__(timeout=1800) # 30 mins
        self.host_id = host_id

    @discord.ui.button(label="✋ Request to Join", style=discord.ButtonStyle.green)
    async def request_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.host_id: return await interaction.response.send_message("❌ You are the host.", ephemeral=True)
        
        await interaction.response.send_message("✅ Request sent to host!", ephemeral=True)
        
        # Notify Host
        host = interaction.guild.get_member(self.host_id)
        if host:
            try:
                view = AcceptTeamRequestView(interaction.user.id, interaction.guild)
                await host.send(f"📩 **{interaction.user.name}** wants to join your team!", view=view)
            except:
                await interaction.channel.send(f"{host.mention}, **{interaction.user.name}** wants to join! (Enable DMs)")

class AcceptTeamRequestView(discord.ui.View):
    def __init__(self, applicant_id, guild):
        super().__init__(timeout=300)
        self.applicant_id = applicant_id
        self.guild = guild

    @discord.ui.button(label="✅ Accept (Create Room)", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        applicant = self.guild.get_member(self.applicant_id)
        if not applicant: return await interaction.response.send_message("❌ User left.", ephemeral=True)
        
        # Create Private Room
        cat = self.guild.get_channel(CAT_PRIVATE_ROOMS)
        overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            applicant: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        chan = await self.guild.create_text_channel(f"team-{interaction.user.name[:5]}-{applicant.name[:5]}", category=cat, overwrites=overwrites)
        
        await interaction.response.send_message(f"✅ Created room: {chan.name}")
        await chan.send(f"👋 **Team Up!**\n{interaction.user.mention} 🤝 {applicant.mention}\nThis room is temporary.")
        self.stop()

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🚫 Request denied.", ephemeral=True)
        self.stop()

@bot.tree.command(name="findteam", description="Find a team (Button System)")
async def findteam(interaction: discord.Interaction, role: str, level: str):
    if interaction.channel.id != CH_FIND_TEAM: return await interaction.response.send_message("❌ Wrong channel.", ephemeral=True)
    
    embed = discord.Embed(title="🎮 Looking for Team", color=discord.Color.orange())
    embed.add_field(name="Player", value=interaction.user.mention, inline=True)
    embed.add_field(name="Role", value=role, inline=True)
    embed.add_field(name="Level", value=level, inline=True)
    embed.set_footer(text="Click button to request join")
    
    await interaction.response.send_message(embed=embed, view=JoinTeamView(interaction.user.id))

# =========================================
# 🛍️ UPGRADE COMMANDS (ADDUSER / ADDTIME)
# =========================================

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
        await interaction.response.send_message(f"✅ {interaction.user.mention} joined!", ephemeral=False)
        
        c_data = col_channels.find_one({"channel_id": self.channel_id})
        if c_data:
            end_time = c_data["end_time"].replace(tzinfo=timezone.utc) if c_data["end_time"].tzinfo is None else c_data["end_time"]
            await update_main_message(interaction.channel, self.owner_id, end_time)
        self.stop()

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id: return
        await interaction.channel.set_permissions(interaction.user, overwrite=None)
        await interaction.response.send_message(f"❌ {interaction.user.mention} declined.", ephemeral=False)
        self.stop()

@bot.tree.command(name="adduser", description="Add user to private room (100 coins)")
async def adduser(interaction: discord.Interaction, user: discord.Member):
    c_data = col_channels.find_one({"channel_id": interaction.channel.id})
    if not c_data or interaction.user.id != c_data["owner_id"]: return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
    if user.id == interaction.user.id or user.bot: return await interaction.response.send_message("❌ Invalid user.", ephemeral=True)
    
    data = get_user_data(interaction.user.id)
    if data["coins"] < COST_ADD_USER: return await interaction.response.send_message(f"❌ Need {COST_ADD_USER} coins.", ephemeral=True)

    await interaction.channel.set_permissions(user, read_messages=True, send_messages=False, connect=False)
    end_time = c_data["end_time"].replace(tzinfo=timezone.utc) if c_data["end_time"].tzinfo is None else c_data["end_time"]
    timestamp = int(end_time.timestamp())
    
    msg = f"📩 **Invite**\n👑 Owner: {interaction.user.mention}\n⏰ Left: <t:{timestamp}:R>\n{user.mention}, accept to join?"
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
# 🔐 PRIVATE CHANNEL CREATION
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
            
            # Send MAIN MESSAGE and store ID
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
# 💰 UTILS (INVITES, COINS, ADMIN)
# =========================================

@bot.tree.command(name="daily", description="Claim coins")
async def daily(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = interaction.user.id
    d = get_user_data(uid)
    now = datetime.now(timezone.utc)
    if d.get("daily_cd") and not is_admin(uid):
        daily_cd = d["daily_cd"].replace(tzinfo=timezone.utc) if d["daily_cd"].tzinfo is None else d["daily_cd"]
        if now < daily_cd: return await interaction.followup.send(f"⏳ Come back in {int((daily_cd - now).total_seconds()//3600)}h.")
    col_users.update_one({"_id": uid}, {"$inc": {"coins": 100}, "$set": {"daily_cd": now + timedelta(hours=24)}})
    await interaction.followup.send(f"💰 +100 Coins!")

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

@bot.tree.command(name="profile", description="Check Stats")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    d = get_user_data(target.id)
    embed = discord.Embed(title=f"👤 {target.name}", color=discord.Color.blue())
    embed.add_field(name="💰 Coins", value=d['coins'])
    embed.add_field(name="🏆 Wins", value=d['wins'])
    embed.add_field(name="🔥 Streak", value=d['streak'])
    embed.add_field(name="⭐ MVPs", value=d['mvp_count'])
    
    # 🆕 Show Team Name
    if d.get("team_id"):
        team = col_teams.find_one({"_id": d["team_id"]})
        if team: embed.add_field(name="🛡️ Team", value=team["name"])
    else:
        embed.add_field(name="🛡️ Team", value="None")
        
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot: return
    # Find team delete logic
    if message.channel.id == CH_FIND_TEAM and not is_admin(message.author.id): await message.delete()
    
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
