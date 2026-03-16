import aiosqlite
import os
os.makedirs("data", exist_ok=True)
DB = "data/void.db"
async def setup_database():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            start_time TEXT,
            end_time TEXT,
            team_size INTEGER,
            ctftime_link TEXT,
            channel_id INTEGER
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS interested(
            event_id INTEGER,
            user_id INTEGER
        )
        """)
        await db.commit()
        await db.execute("""
        CREATE TABLE IF NOT EXISTS event_users(
            event_id INTEGER,
            user_id INTEGER,
            role TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS event_selected(
        event_id INTEGER,
        user_id INTEGER
        )
        """)