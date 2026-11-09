import asyncio, os, logging
from .handlers.discord_handler import DiscordHandler
from .storage import Database

def run():
    asyncio.run(_main())

async def _main():
    logging.info("Initializing Discord bot")
    # Read in configurations and credentials
    DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
    OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
    PINECONE_API_KEY = os.environ['PINECONE_API_KEY']

    # Initialize the main DiscordHandler
    discord_bot = DiscordHandler(DISCORD_TOKEN, OPENAI_API_KEY, PINECONE_API_KEY)

    # Opt-in until the persistent volume is mounted in each environment.
    # Never silently fall back to a database in the container filesystem.
    database = None
    try:
        database_path = os.getenv("DISCORD_SQLITE_PATH")
        if database_path:
            database = Database(database_path).open()
            database.integrity_check()
            logging.info("SQLite storage initialized")
        await discord_bot.start()
    finally:
        try:
            await discord_bot.shutdown()
        finally:
            if database is not None:
                database.close()

