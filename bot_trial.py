import discord
from discord.ext import commands
from discord import app_commands
from config import TOKEN
import aiosqlite
from database import DB
from database import setup_database
import os, time
from discord.ext import tasks
from datetime import datetime
import re

APPLICATION_CHANNEL_ID = 1474752560198979794
PROOF_LOG_CHANNEL_ID = 1474752560198979794

os.makedirs("data", exist_ok=True)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix="!", intents=intents)

def convert_to_timestamp(time_string):
    try:
        dt = datetime.strptime(time_string, "%m/%d/%y, %I:%M %p")
    except ValueError:
        dt = datetime.strptime(time_string, "%Y-%m-%d %H:%M")
    return int(dt.timestamp())

async def build_dashboard_embed():
    now = int(time.time())
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, name, start_ts, end_ts, ctftime_link FROM events WHERE end_ts >= ? ORDER BY start_ts ASC",
            (now,))
        events = await cursor.fetchall()
    if not events:
        embed = discord.Embed(
            title="VOID WALKERS CTF CONTROL PANEL",
            description="No upcoming events.",
            color=0x00ffcc)
        return embed
    embed = discord.Embed(title="VOID WALKERS CTF CONTROL PANEL", color=0x00ffcc)
    for event in events:
        event_id, name, start_ts, end_ts, ctftime_link = event
        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='interested'", (event_id,))
            interested_count = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='captain'", (event_id,))
            captain_count = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_selected WHERE event_id=?", (event_id,))
            selected_count = (await cursor.fetchone())[0]
        if now < start_ts:
            status = "⏳ Upcoming"
        elif now >= start_ts and now <= end_ts:
            status = "� Live"
        else:
            status = "✅ Ended"
        embed.add_field(
            name=f"{status} — {name}",
            value=f"Start: <t:{start_ts}:R>\nEnd: <t:{end_ts}:R>\n[CTFTime]({ctftime_link})\n� Interested: {interested_count} | �️ Captains: {captain_count} | ⚔️ Team: {selected_count}",
            inline=False)
    return embed

@bot.event
async def on_ready():
    await setup_database()
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, name, start_ts, end_ts FROM events WHERE end_ts >= ?",
            (int(time.time()),))
        events = await cursor.fetchall()
        for event in events:
            event_id, name, start_ts, end_ts = event
            bot.add_view(EventView(event_id, name, start_ts, end_ts))
    await bot.tree.sync()
    if not event_start_checker.is_running():
        event_start_checker.start()
    if not proof_reminder.is_running():
        proof_reminder.start()
    if not dashboard_updater.is_running():
        dashboard_updater.start()
    print(f"{bot.user} is online")

@bot.tree.command(name="ping", description="Check if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("VoidWalkers bot operational ⚡")

@bot.tree.command(name="dashboard", description="Show all scheduled CTF events")
async def dashboard(interaction: discord.Interaction):
    embed = await build_dashboard_embed()
    await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM dashboard_messages")
        await db.execute("INSERT INTO dashboard_messages VALUES (?,?)",
            (interaction.channel.id, message.id))
        await db.commit()

def update_embed_counts(embed, interested_count, captain_count):
    for i, field in enumerate(embed.fields):
        if field.name == "Interested Players":
            embed.set_field_at(i, name="Interested Players", value=str(interested_count), inline=False)
        elif field.name == "Captain Applications":
            embed.set_field_at(i, name="Captain Applications", value=str(captain_count), inline=False)
    return embed

async def refresh_dashboard(client):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT channel_id, message_id FROM dashboard_messages")
        row = await cursor.fetchone()
    if not row:
        return
    channel_id, message_id = row
    channel = client.get_channel(channel_id)
    if not channel:
        return
    try:
        message = await channel.fetch_message(message_id)
        embed = await build_dashboard_embed()
        await message.edit(embed=embed)
    except:
        pass

class EventView(discord.ui.View):
    def __init__(self, event_id, event_name, start_ts, end_ts):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.event_name = event_name
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.interested_button.custom_id = f"interested_{event_id}"
        self.captain_button.custom_id = f"captain_{event_id}"

    @discord.ui.button(label="Interested", style=discord.ButtonStyle.green, custom_id="interested_placeholder")
    async def interested_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if int(time.time()) > self.start_ts:
            await interaction.response.send_message("❌ Registration is closed, event has already started.", ephemeral=True)
            return
        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT role FROM event_users WHERE event_id=? AND user_id=?",
                (self.event_id, interaction.user.id))
            exists = await cursor.fetchone()
            if exists:
                await interaction.response.send_message(
                    f"You are already registered as **{exists[0]}** for this event.", ephemeral=True)
                return
            await db.execute(
                "INSERT INTO event_users VALUES (?,?,?)",
                (self.event_id, interaction.user.id, "interested"))
            await db.commit()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='interested'", (self.event_id,))
            interested_count = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='captain'", (self.event_id,))
            captain_count = (await cursor.fetchone())[0]
        embed = interaction.message.embeds[0]
        embed = update_embed_counts(embed, interested_count, captain_count)
        await interaction.response.send_message("✅ Registered successfully!", ephemeral=True)
        await interaction.message.edit(embed=embed)
        channel = interaction.client.get_channel(APPLICATION_CHANNEL_ID)
        await channel.send(
            f"⭐ **Interested Player**\nUser: {interaction.user.mention}\nEvent: {self.event_name}")
        await refresh_dashboard(interaction.client)
        
    @discord.ui.button(label="Apply Captain", style=discord.ButtonStyle.blurple, custom_id="captain_placeholder")
    async def captain_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if int(time.time()) > self.start_ts:
            await interaction.response.send_message("❌ Registration is closed, event has already started.", ephemeral=True)
            return
        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT role FROM event_users WHERE event_id=? AND user_id=?",
                (self.event_id, interaction.user.id))
            exists = await cursor.fetchone()
            if exists:
                await interaction.response.send_message(
                    f"You are already registered as **{exists[0]}** for this event.", ephemeral=True)
                return
            await db.execute(
                "INSERT INTO event_users VALUES (?,?,?)",
                (self.event_id, interaction.user.id, "captain"))
            await db.commit()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='interested'", (self.event_id,))
            interested_count = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_users WHERE event_id=? AND role='captain'", (self.event_id,))
            captain_count = (await cursor.fetchone())[0]
        embed = interaction.message.embeds[0]
        embed = update_embed_counts(embed, interested_count, captain_count)
        await interaction.response.send_message("✅ Registered as Captain!", ephemeral=True)
        await interaction.message.edit(embed=embed)
        channel = interaction.client.get_channel(APPLICATION_CHANNEL_ID)
        await channel.send(
            f"�️ **Captain Application**\nUser: {interaction.user.mention}\nEvent: {self.event_name}")
        await refresh_dashboard(interaction.client)
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
            "❌ Invalid time format.\nUse: `3/15/26, 9:48 PM`", ephemeral=True)
        return
    start_display = datetime.fromtimestamp(start_ts).strftime("%b %d, %Y %I:%M %p")
    end_display = datetime.fromtimestamp(end_ts).strftime("%b %d, %Y %I:%M %p")
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "INSERT INTO events(name,start_time,end_time,start_ts,end_ts,team_size,ctftime_link,channel_id) VALUES(?,?,?,?,?,?,?,?)",
            (name, start_time, end_time, start_ts, end_ts, team_size, ctftime_link, discussion_channel.id))
        event_id = cursor.lastrowid
        await db.commit()
    embed = discord.Embed(title=f"⚔️ {name}", description="New CTF Event", color=0x00ffcc)
    embed.add_field(name="Start Time", value=f"{start_display} (<t:{start_ts}:R>)", inline=False)
    embed.add_field(name="End Time", value=f"{end_display} (<t:{end_ts}:R>)", inline=False)
    embed.add_field(name="Team Size", value="Unlimited" if team_size == 0 else team_size, inline=True)
    embed.add_field(name="CTFTime", value=ctftime_link, inline=False)
    embed.add_field(name="Discussion Channel", value=discussion_channel.mention, inline=False)
    embed.add_field(name="Interested Players", value="0", inline=False)
    embed.add_field(name="Captain Applications", value="0", inline=False)
    view = EventView(event_id, name, start_ts, end_ts)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="manage_event", description="Send event access details to players")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    mode="Choose how players will join the event",
    event_id="Select the event",
    event_name="Name of the event",
    captain="Captain of the team",
    players="Mention players separated by space",
    team_name="Team name (for credential mode)",
    team_password="Team password (for credential mode)",
    invite_link="Invite link (for invite mode)")
@app_commands.choices(mode=[
    app_commands.Choice(name="Team Credentials", value="team"),
    app_commands.Choice(name="Invite Link", value="invite")])
async def manage_event(
    interaction: discord.Interaction,
    mode: str,
    event_id: int,
    captain: discord.Member,
    players: str,
    team_name: str = None,
    event_name: str = None,
    team_password: str = None,
    invite_link: str = None):
    await interaction.response.send_message("Sending team information...", ephemeral=True)
    user_ids = [int(uid) for uid in re.findall(r'\d+', players)]
    success = 0
    failed = 0
    for uid in user_ids:
        member = interaction.guild.get_member(uid)
        if not member:
            failed += 1
            continue
        try:
            if mode == "team":
                embed = discord.Embed(title="⚔️ CTF Team Assignment", color=0x00ffcc)
                embed.add_field(name="Event", value=event_name, inline=False)
                embed.add_field(name="Team Name", value=team_name, inline=False)
                embed.add_field(name="Team Password", value=team_password, inline=False)
                embed.add_field(name="Captain", value=captain.mention, inline=False)
            elif mode == "invite":
                embed = discord.Embed(title="⚔️ CTF Event Invitation", color=0x00ffcc)
                embed.add_field(name="Event", value=event_name, inline=False)
                embed.add_field(name="Invite Link", value=invite_link, inline=False)
                embed.add_field(name="Captain", value=captain.mention, inline=False)
            await member.send(embed=embed)
            async with aiosqlite.connect(DB) as db:
                await db.execute("INSERT INTO event_selected VALUES (?,?)", (event_id, member.id))
                await db.commit()
            success += 1
        except:
            failed += 1
    await interaction.followup.send(f"✅ Sent to {success} players\n❌ Failed: {failed}", ephemeral=True)

@manage_event.autocomplete("event_id")
async def manage_event_autocomplete(interaction: discord.Interaction, current: str):
    now = int(time.time())
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, name FROM events WHERE end_ts >= ? ORDER BY start_ts DESC", (now,))
        events = await cursor.fetchall()
    return [
        app_commands.Choice(name=f"{name} (ID: {event_id})", value=event_id)
        for event_id, name in events
        if current.lower() in name.lower()
    ]

@manage_event.error
async def manage_event_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)

@bot.tree.command(name="edit_event", description="Edit a CTF event")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    event_id="Select the event to edit",
    name="New name",
    start_time="New start time e.g. 3/21/26, 6:00 PM",
    end_time="New end time e.g. 3/22/26, 6:00 PM",
    team_size="New team size (0 = unlimited)",
    ctftime_link="New CTFTime link")
async def edit_event(
    interaction: discord.Interaction,
    event_id: int,
    name: str = None,
    start_time: str = None,
    end_time: str = None,
    team_size: int = None,
    ctftime_link: str = None):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT name, start_time, end_time, start_ts, end_ts, team_size, ctftime_link FROM events WHERE id=?",
            (event_id,))
        event = await cursor.fetchone()
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
        cur_name, cur_start_time, cur_end_time, cur_start_ts, cur_end_ts, cur_team_size, cur_ctftime = event
        new_name = name or cur_name
        new_team_size = team_size if team_size is not None else cur_team_size
        new_ctftime = ctftime_link or cur_ctftime
        if start_time:
            try:
                new_start_ts = convert_to_timestamp(start_time)
                new_start_time = start_time
            except:
                await interaction.response.send_message("❌ Invalid start time format.", ephemeral=True)
                return
        else:
            new_start_ts = cur_start_ts
            new_start_time = cur_start_time
        if end_time:
            try:
                new_end_ts = convert_to_timestamp(end_time)
                new_end_time = end_time
            except:
                await interaction.response.send_message("❌ Invalid end time format.", ephemeral=True)
                return
        else:
            new_end_ts = cur_end_ts
            new_end_time = cur_end_time
        await db.execute(
            "UPDATE events SET name=?, start_time=?, end_time=?, start_ts=?, end_ts=?, team_size=?, ctftime_link=? WHERE id=?",
            (new_name, new_start_time, new_end_time, new_start_ts, new_end_ts, new_team_size, new_ctftime, event_id))
        await db.commit()
    await interaction.response.send_message(f"✅ Event **{new_name}** updated successfully!", ephemeral=True)

@edit_event.autocomplete("event_id")
async def edit_event_autocomplete(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT id, name FROM events ORDER BY start_ts DESC")
        events = await cursor.fetchall()
    return [
        app_commands.Choice(name=f"{name} (ID: {event_id})", value=event_id)
        for event_id, name in events
        if current.lower() in name.lower()
    ]

@bot.tree.command(name="delete_event", description="Delete a CTF event")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(event_id="Select the event to delete")
async def delete_event(interaction: discord.Interaction, event_id: int):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT name FROM events WHERE id=?", (event_id,))
        event = await cursor.fetchone()
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
        event_name = event[0]
        await db.execute("DELETE FROM events WHERE id=?", (event_id,))
        await db.execute("DELETE FROM event_users WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM event_selected WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM clock_sessions WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM activity_proofs WHERE event_id=?", (event_id,))
        await db.execute("DELETE FROM player_stats WHERE event_id=?", (event_id,))
        await db.commit()
    await interaction.response.send_message(
        f"✅ Event **{event_name}** and all related data deleted.", ephemeral=True)

@delete_event.autocomplete("event_id")
async def delete_event_autocomplete(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT id, name FROM events ORDER BY start_ts DESC")
        events = await cursor.fetchall()
    return [
        app_commands.Choice(name=f"{name} (ID: {event_id})", value=event_id)
        for event_id, name in events
        if current.lower() in name.lower()
    ]

@bot.tree.command(name="clockin", description="Clock in to start tracking your CTF activity")
async def clockin(interaction: discord.Interaction):
    now = int(time.time())
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, name FROM events WHERE start_ts <= ? AND end_ts >= ?", (now, now))
        event = await cursor.fetchone()
        if not event:
            await interaction.response.send_message("❌ No active CTF event right now.", ephemeral=True)
            return
        event_id, event_name = event
        cursor = await db.execute(
            "SELECT * FROM event_selected WHERE event_id=? AND user_id=?",
            (event_id, interaction.user.id))
        selected = await cursor.fetchone()
        if not selected:
            await interaction.response.send_message("❌ You are not part of this event's team.", ephemeral=True)
            return
        cursor = await db.execute(
            "SELECT * FROM clock_sessions WHERE event_id=? AND user_id=? AND is_active=1",
            (event_id, interaction.user.id))
        active = await cursor.fetchone()
        if active:
            await interaction.response.send_message("⚠️ You are already clocked in!", ephemeral=True)
            return
        await db.execute(
            "INSERT INTO clock_sessions(event_id, user_id, clock_in_time, is_active) VALUES (?,?,?,1)",
            (event_id, interaction.user.id, now))
        await db.commit()
    await interaction.response.send_message(
        f"✅ Clocked in for **{event_name}**!\n"
        f"⏱️ You will be pinged every hour to submit proof.\n"
        f"Use `/proof` to submit screenshots of your progress.",
        ephemeral=True)

@bot.tree.command(name="clockout", description="Clock out to stop tracking your CTF activity")
async def clockout(interaction: discord.Interaction):
    now = int(time.time())
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, event_id, clock_in_time FROM clock_sessions WHERE user_id=? AND is_active=1",
            (interaction.user.id,))
        session = await cursor.fetchone()
        if not session:
            await interaction.response.send_message("❌ You are not clocked in.", ephemeral=True)
            return
        session_id, event_id, clock_in_time = session
        total_minutes = (now - clock_in_time) // 60
        await db.execute(
            "UPDATE clock_sessions SET clock_out_time=?, is_active=0 WHERE id=?", (now, session_id))
        cursor = await db.execute(
            "SELECT * FROM player_stats WHERE user_id=? AND event_id=?",
            (interaction.user.id, event_id))
        stats = await cursor.fetchone()
        if stats:
            await db.execute(
                "UPDATE player_stats SET total_minutes=total_minutes+? WHERE user_id=? AND event_id=?",
                (total_minutes, interaction.user.id, event_id))
        else:
            await db.execute(
                "INSERT INTO player_stats(user_id, event_id, total_minutes) VALUES (?,?,?)",
                (interaction.user.id, event_id, total_minutes))
        await db.commit()
    hours = total_minutes // 60
    minutes = total_minutes % 60
    await interaction.response.send_message(
        f"✅ Clocked out!\n⏱️ Active time this session: **{hours}h {minutes}m**",
        ephemeral=True)

@bot.tree.command(name="proof", description="Submit proof of your CTF activity")
@app_commands.describe(
    challenge_type="Type of challenge you are working on",
    screenshot="Screenshot of your progress")
@app_commands.choices(challenge_type=[
    app_commands.Choice(name="Web", value="web"),
    app_commands.Choice(name="OSINT", value="osint"),
    app_commands.Choice(name="Exploit/PWN", value="exploit"),
    app_commands.Choice(name="Reverse Engineering", value="rev"),
    app_commands.Choice(name="Cryptography", value="crypto"),
    app_commands.Choice(name="Other", value="other")])
async def proof(
    interaction: discord.Interaction,
    challenge_type: str,
    screenshot: discord.Attachment):
    now = int(time.time())
    if not screenshot.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Please upload an image file.", ephemeral=True)
        return
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, event_id FROM clock_sessions WHERE user_id=? AND is_active=1",
            (interaction.user.id,))
        session = await cursor.fetchone()
        if not session:
            await interaction.response.send_message("❌ You are not clocked in. Use `/clockin` first.", ephemeral=True)
            return
        session_id, event_id = session
        cursor = await db.execute(
            "SELECT * FROM activity_proofs WHERE session_id=? AND submitted_at >= ?",
            (session_id, now - 3600))
        recent = await cursor.fetchone()
        if recent:
            await interaction.response.send_message(
                "⚠️ You already submitted proof in the last hour. Wait for the next ping!", ephemeral=True)
            return
        await db.execute(
            "INSERT INTO activity_proofs(session_id, user_id, event_id, proof_url, challenge_type, submitted_at) VALUES (?,?,?,?,?,?)",
            (session_id, interaction.user.id, event_id, screenshot.url, challenge_type, now))
        cursor = await db.execute(
            "SELECT * FROM player_stats WHERE user_id=? AND event_id=?",
            (interaction.user.id, event_id))
        stats = await cursor.fetchone()
        if stats:
            await db.execute(
                "UPDATE player_stats SET proof_count=proof_count+1 WHERE user_id=? AND event_id=?",
                (interaction.user.id, event_id))
        else:
            await db.execute(
                "INSERT INTO player_stats(user_id, event_id, proof_count) VALUES (?,?,1)",
                (interaction.user.id, event_id))
        await db.commit()
    import aiohttp
    import io
    proof_log_channel = interaction.client.get_channel(PROOF_LOG_CHANNEL_ID)
    if proof_log_channel:
        async with aiohttp.ClientSession() as session:
            async with session.get(screenshot.url) as resp:
                if resp.status == 200:
                    image_data = await resp.read()
                else:
                    image_data = None
        if image_data:
            log_message = await proof_log_channel.send(
                f"� **Proof Log**\nUser: {interaction.user.mention}\nChallenge: **{challenge_type}**\nEvent ID: `{event_id}`",
                file=discord.File(fp=io.BytesIO(image_data), filename=screenshot.filename))
            permanent_url = log_message.attachments[0].url
            async with aiosqlite.connect(DB) as db:
                await db.execute(
                    "UPDATE activity_proofs SET proof_url=? WHERE user_id=? AND event_id=? AND submitted_at=?",
                    (permanent_url, interaction.user.id, event_id, now))
                await db.commit()
    await interaction.response.send_message(
        f"✅ Proof submitted!\nChallenge type: **{challenge_type}**\nKeep it up! Next proof in 1 hour. �",
        ephemeral=True)

@bot.tree.command(name="stats", description="Check your CTF activity stats")
@app_commands.describe(event_id="Select the event")
async def stats(interaction: discord.Interaction, event_id: int):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT name FROM events WHERE id=?", (event_id,))
        event = await cursor.fetchone()
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
        event_name = event[0]
        cursor = await db.execute(
            "SELECT total_minutes, proof_count FROM player_stats WHERE user_id=? AND event_id=?",
            (interaction.user.id, event_id))
        stats_row = await cursor.fetchone()
        if not stats_row:
            await interaction.response.send_message("❌ No activity found for this event.", ephemeral=True)
            return
        total_minutes, proof_count = stats_row
        cursor = await db.execute(
            "SELECT challenge_type, COUNT(*) FROM activity_proofs WHERE user_id=? AND event_id=? GROUP BY challenge_type",
            (interaction.user.id, event_id))
        challenge_breakdown = await cursor.fetchall()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM clock_sessions WHERE user_id=? AND event_id=?",
            (interaction.user.id, event_id))
        session_count = (await cursor.fetchone())[0]
    hours = total_minutes // 60
    minutes = total_minutes % 60
    embed = discord.Embed(
        title=f"� Stats — {interaction.user.display_name}",
        description=f"Event: **{event_name}**",
        color=0x00ffcc)
    embed.add_field(name="Total Active Time", value=f"{hours}h {minutes}m", inline=True)
    embed.add_field(name="Proofs Submitted", value=str(proof_count), inline=True)
    embed.add_field(name="Sessions", value=str(session_count), inline=True)
    if challenge_breakdown:
        breakdown_text = "\n".join([f"{ctype}: {count}" for ctype, count in challenge_breakdown])
        embed.add_field(name="Challenge Breakdown", value=breakdown_text, inline=False)
    await interaction.response.send_message(embed=embed)

@stats.autocomplete("event_id")
async def stats_event_autocomplete(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT id, name FROM events ORDER BY start_ts DESC")
        events = await cursor.fetchall()
    return [
        app_commands.Choice(name=f"{name} (ID: {event_id})", value=event_id)
        for event_id, name in events
        if current.lower() in name.lower()
    ]

@bot.tree.command(name="leaderboard", description="See activity leaderboard for an event")
@app_commands.describe(event_id="Select the event")
async def leaderboard(interaction: discord.Interaction, event_id: int):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT name FROM events WHERE id=?", (event_id,))
        event = await cursor.fetchone()
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
        event_name = event[0]
        cursor = await db.execute(
            "SELECT user_id, total_minutes, proof_count FROM player_stats WHERE event_id=? ORDER BY total_minutes DESC, proof_count DESC",
            (event_id,))
        players = await cursor.fetchall()
    if not players:
        await interaction.response.send_message("❌ No activity data for this event yet.", ephemeral=True)
        return
    embed = discord.Embed(title=f"� Leaderboard — {event_name}", color=0x00ffcc)
    medals = ["�", "�", "�"]
    leaderboard_text = ""
    for i, (user_id, total_minutes, proof_count) in enumerate(players):
        hours = total_minutes // 60
        minutes = total_minutes % 60
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        try:
            user = await bot.fetch_user(user_id)
            name = user.display_name
        except:
            name = f"User {user_id}"
        leaderboard_text += f"{medal} **{name}** — {hours}h {minutes}m | {proof_count} proofs\n"
    embed.add_field(name="Rankings", value=leaderboard_text, inline=False)
    await interaction.response.send_message(embed=embed)

@leaderboard.autocomplete("event_id")
async def leaderboard_event_autocomplete(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT id, name FROM events ORDER BY start_ts DESC")
        events = await cursor.fetchall()
    return [
        app_commands.Choice(name=f"{name} (ID: {event_id})", value=event_id)
        for event_id, name in events
        if current.lower() in name.lower()
    ]

@tasks.loop(minutes=1)
async def event_start_checker():
    now = int(time.time())
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, name, ctftime_link, start_ts FROM events WHERE notified=0")
        events = await cursor.fetchall()
        for event in events:
            event_id, name, link, start_ts = event
            if abs(now - start_ts) <= 60:
                cursor = await db.execute(
                    "SELECT user_id FROM event_selected WHERE event_id=?", (event_id,))
                players = await cursor.fetchall()
                for player in players:
                    try:
                        user = await bot.fetch_user(player[0])
                        embed = discord.Embed(
                            title=f"� {name} has started!",
                            description=f"The CTF is now live!\n\n{link}",
                            color=0xff0000)
                        await user.send(embed=embed)
                    except:
                        pass
                await db.execute(
                    "UPDATE events SET notified=1 WHERE id=?", (event_id,))
                await db.commit()

@tasks.loop(minutes=1)
async def proof_reminder():
    now = int(time.time())
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT id, user_id, clock_in_time, event_id FROM clock_sessions WHERE is_active=1")
        sessions = await cursor.fetchall()
        for session in sessions:
            session_id, user_id, clock_in_time, event_id = session
            cursor = await db.execute(
                "SELECT submitted_at FROM activity_proofs WHERE session_id=? ORDER BY submitted_at DESC LIMIT 1",
                (session_id,))
            last_proof = await cursor.fetchone()
            last_time = last_proof[0] if last_proof else clock_in_time
            elapsed = now - last_time
            if 3600 <= elapsed < 3660:
                try:
                    user = await bot.fetch_user(user_id)
                    await user.send(
                        f"⏰ **Proof reminder!**\n"
                        f"1 hour has passed! Submit your proof using `/proof`\n"
                        f"You have **10 minutes** before you are clocked out automatically.")
                except:
                    pass
            elif 3900 <= elapsed < 3960:
                try:
                    user = await bot.fetch_user(user_id)
                    await user.send(
                        f"⚠️ **Last warning!**\n"
                        f"5 minutes left! Submit your proof using `/proof`\n"
                        f"If you don't submit in 5 minutes, you will be **automatically clocked out**.")
                except:
                    pass
            elif elapsed >= 4200:
                total_minutes = (last_time - clock_in_time) // 60
                await db.execute(
                    "UPDATE clock_sessions SET clock_out_time=?, is_active=0 WHERE id=?",
                    (now, session_id))
                cursor = await db.execute(
                    "SELECT * FROM player_stats WHERE user_id=? AND event_id=?",
                    (user_id, event_id))
                stats = await cursor.fetchone()
                if stats:
                    await db.execute(
                        "UPDATE player_stats SET total_minutes=total_minutes+? WHERE user_id=? AND event_id=?",
                        (total_minutes, user_id, event_id))
                else:
                    await db.execute(
                        "INSERT INTO player_stats(user_id, event_id, total_minutes) VALUES (?,?,?)",
                        (user_id, event_id, total_minutes))
                await db.commit()
                hours = total_minutes // 60
                minutes = total_minutes % 60
                try:
                    user = await bot.fetch_user(user_id)
                    await user.send(
                        f"**Automatically clocked out!**\n"
                        f"You did not submit proof in time.\n"
                        f"Your recorded active time: **{hours}h {minutes}m**\n"
                        f"Use `/clockin` to start a new session.")
                except:
                    pass

@tasks.loop(minutes=5)
async def dashboard_updater():
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT channel_id, message_id FROM dashboard_messages")
        row = await cursor.fetchone()
    if not row:
        return
    channel_id, message_id = row
    channel = bot.get_channel(channel_id)
    if not channel:
        return
    try:
        message = await channel.fetch_message(message_id)
        embed = await build_dashboard_embed()
        await message.edit(embed=embed)
    except:
        pass

bot.run(TOKEN)