import asyncio, os, logging
from .handlers.discord_handler import DiscordHandler

def run():
    asyncio.run(_main())

async def _main():
    # Read in configurations and credentials
    DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
    OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
    PINECONE_API_KEY = os.environ['PINECONE_API_KEY']

    # Initialize the main DiscordHandler
    discord_bot = DiscordHandler(DISCORD_TOKEN, OPENAI_API_KEY, PINECONE_API_KEY)

    # Start the bot and handle shutdown
    try:
        await discord_bot.start()
    except KeyboardInterrupt:
        print("Shutting down...")
        await discord_bot.shutdown()

