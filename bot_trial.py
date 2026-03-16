import discord
from discord.ext import commands
from discord import app_commands
from config import TOKEN
import aiosqlite
from database import DB
from database import setup_database
import os, time
from discord.ext import tasks

APPLICATION_CHANNEL_ID = 1474752560198979794  # replace with your channel ID
os.makedirs("data", exist_ok=True)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
event_embed = None
event_message = None
bot = commands.Bot(command_prefix="!", intents=intents)
from datetime import datetime
def convert_to_timestamp(time_string):
    try:
        dt = datetime.strptime(time_string, "%m/%d/%y, %I:%M %p")
    except ValueError:
        dt = datetime.strptime(time_string, "%Y-%m-%d %H:%M")
    return int(dt.timestamp())
@bot.event
async def on_ready():
    await bot.tree.sync()
    if not event_start_checker.is_running():
        event_start_checker.start()
    print(f"{bot.user} is online")
@bot.tree.command(name="ping", description="Check if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("VoidWalkers bot operational ⚡")
@bot.tree.command(name="dashboard", description="Create CTF dashboard")
async def dashboard(interaction: discord.Interaction):
    global event_embed
    global event_message
    event_embed = discord.Embed(
        title="VOID WALKERS CTF CONTROL PANEL",
        description="Upcoming events will appear here.",
        color=0x00ffcc)
    event_embed.add_field(
        name="Upcoming CTF",
        value="None",
        inline=False)
    event_embed.add_field(
        name="Interested Players",
        value="0",
        inline=False)
    await interaction.response.send_message(embed=event_embed)
    event_message = await interaction.original_response()
@app_commands.checks.has_permissions(administrator=True)
class EventView(discord.ui.View):
    def __init__(self, event_id, event_name, end_ts):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.event_name = event_name
        self.end_ts = end_ts  
    @discord.ui.button(label="Interested", style=discord.ButtonStyle.green, emoji="⭐")
    async def interested(self, interaction: discord.Interaction, button: discord.ui.Button):
        if int(time.time()) > self.end_ts:
            await interaction.response.send_message(
                "❌ The event registration is over.",
                ephemeral=True)
            return
        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT * FROM event_users WHERE event_id=? AND user_id=?",
                (self.event_id, interaction.user.id))
            exists = await cursor.fetchone()
            if exists:
                await interaction.response.send_message(
                    "You already registered.",
                    ephemeral=True)
                return
            await db.execute(
                "INSERT INTO event_users VALUES (?,?,?)",
                (self.event_id, interaction.user.id, "interested"))
            await db.commit()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='interested'",
                (self.event_id,))
            interested_count = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='captain'",
                (self.event_id,))
            captain_count = (await cursor.fetchone())[0]
        embed = interaction.message.embeds[0]
        embed.set_field_at(3, name="Interested Players", value=str(interested_count), inline=False)
        embed.set_field_at(4, name="Captain Applications", value=str(captain_count), inline=False)
        await interaction.message.edit(embed=embed)
        await interaction.response.send_message(
            "✅ Registered successfully!",
            ephemeral=True)
        channel = interaction.client.get_channel(APPLICATION_CHANNEL_ID)
        await channel.send(
            f"⭐ **Interested Player**\n"
            f"User: {interaction.user.mention}\n"
            f"Event: {self.event_name}"
        )
    @discord.ui.button(label="Apply Captain", style=discord.ButtonStyle.blurple, emoji="🧭")
    async def captain(self, interaction: discord.Interaction, button: discord.ui.Button):
        if int(time.time()) > self.end_ts:
            await interaction.response.send_message(
                "❌ The event registration is over.",
                ephemeral=True)
            return
        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT * FROM event_users WHERE event_id=? AND user_id=?",
                (self.event_id, interaction.user.id))
            exists = await cursor.fetchone()
            if exists:
                await interaction.response.send_message(
                    "You already registered.",
                    ephemeral=True)
                return
            await db.execute(
                "INSERT INTO event_users VALUES (?,?,?)",
                (self.event_id, interaction.user.id, "captain"))
            await db.commit()
            channel = interaction.client.get_channel(APPLICATION_CHANNEL_ID)
            await channel.send(
                f"🧭 **Captain Application**\n"
                f"User: {interaction.user.mention}\n"
                f"Event: {self.event_name}")
@bot.tree.command(name="event_registration", description="Create a CTF event")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    name="Name of the CTF event",
    start_time="Example: 3/15/26, 9:41 PM",
    end_time="Example: 3/16/26, 9:41 PM",
    team_size="Maximum players per team (0 = unlimited)",
    ctftime_link="Link to the event on CTFTime",
    discussion_channel="Channel where players will discuss the CTF")
async def event_registration(
    interaction: discord.Interaction,
    name: str,
    start_time: str,
    end_time: str,
    team_size: int,
    ctftime_link: str,
    discussion_channel: discord.TextChannel):
    try:
        start_ts = convert_to_timestamp(start_time)
        end_ts = convert_to_timestamp(end_time)
    except Exception:
        await interaction.response.send_message(
        "❌ Invalid time format.\nUse: `3/15/26, 9:48 PM`",
        ephemeral=True)
    start_display = datetime.fromtimestamp(start_ts).strftime("%b %d, %Y %I:%M %p")
    end_display = datetime.fromtimestamp(end_ts).strftime("%b %d, %Y %I:%M %p")
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            """
            INSERT INTO events(name,start_time,end_time,team_size,ctftime_link,channel_id)
            VALUES(?,?,?,?,?,?)
            """,
            (name, start_time, end_time, team_size, ctftime_link, discussion_channel.id))
        event_id = cursor.lastrowid
        await db.commit()
    # Create embed
    embed = discord.Embed(
        title=f"⚔️ {name}",
        description="New CTF Event",
        color=0x00ffcc)
    embed.add_field(
    name="Start Time",
    value=f"{start_display} (<t:{start_ts}:R>)",
    inline=False)
    embed.add_field(
    name="End Time",
    value=f"{end_display} (<t:{end_ts}:R>)",
    inline=False)
    embed.add_field(
        name="Team Size",
        value="Unlimited" if team_size == 0 else team_size,
        inline=True)
    embed.add_field(name="CTFTime", 
                    value=ctftime_link, 
                    inline=False)
    embed.add_field(name="Discussion Chanel", 
                    value=discussion_channel.mention, 
                    inline=False)
    view = EventView(event_id, name, end_ts)
    await interaction.response.send_message(
    embed=embed,
    view=view)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(mode=[
    app_commands.Choice(name="Team Credentials", value="team"),
    app_commands.Choice(name="Invite Link", value="invite")])
@bot.tree.command(name="manage_event", description="Send event access details to players")
@app_commands.describe(
    mode="Choose how players will join the event",
    event_name="Name of the event (for reference)",
    team_name="Team name (for credential mode)",
    team_password="Team password (for credential mode)",
    invite_link="Invite link (for invite mode)",
    captain="Captain of the team",
    players="Mention players separated by space")
async def manage_event(
    interaction: discord.Interaction,
    mode: str,
    event_id: int,
    captain: discord.Member,
    players: str,
    team_name: str = None,
    event_name: str = None,
    team_password: str = None,
    invite_link: str = None
):
    await interaction.response.send_message(
        "Sending team information...",
        ephemeral=True)
    user_ids = [int(x.strip("<@!>")) for x in players.split()]
    success = 0
    failed = 0
    for uid in user_ids:
        member = interaction.guild.get_member(uid)
        if not member:
            failed += 1
            continue
        try:
            if mode == "team":
                embed = discord.Embed(
                    title="⚔️ CTF Team Assignment",
                    color=0x00ffcc)
                embed.add_field(name="Event", value=event_name, inline=False)
                embed.add_field(name="Team Name", value=team_name, inline=False)
                embed.add_field(name="Team Password", value=team_password, inline=False)
                embed.add_field(name="Captain", value=captain.mention, inline=False)
            elif mode == "invite":
                embed = discord.Embed(
                    title="⚔️ CTF Event Invitation",
                    color=0x00ffcc)
                embed.add_field(name="Event", value=event_name, inline=False)
                embed.add_field(name="Invite Link", value=invite_link, inline=False)
                embed.add_field(name="Captain", value=captain.mention, inline=False)
            await member.send(embed=embed)
            async with aiosqlite.connect(DB) as db:
                await db.execute(
                    "INSERT INTO event_selected VALUES (?,?)",
                    (event_id, member.id)
                )
                await db.commit()
            success += 1
            
        except:
            failed += 1
    await interaction.followup.send(
        f"✅ Sent to {success} players\n❌ Failed: {failed}",
        ephemeral=True)
@manage_event.error
async def manage_event_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.",
            ephemeral=True)



@tasks.loop(minutes=1)
async def event_start_checker():
    now = int(time.time())
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
        "SELECT id,name,ctftime_link,start_ts FROM events")
        events = await cursor.fetchall()
        for event in events:
            event_id, name, link, start_ts = event
            if abs(now - start_ts) <= 60:
                cursor = await db.execute(
                "SELECT user_id FROM event_selected WHERE event_id=?",
                (event_id,))
                players = await cursor.fetchall()
                for player in players:
                    try:
                        user = await bot.fetch_user(player[0])
                        embed = discord.Embed(
                            title=f"🚨 {name} has started!",
                            description=f"The CTF is now live!\n\n{link}",
                            color=0xff0000)
                        await user.send(embed=embed)
                    except:
                        pass
bot.run(TOKEN)