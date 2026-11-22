import asyncio, os, logging
from .functions.read_youtube import ReadYouTube
from .handlers.chatgpt_handler import GPT_MODEL
from .handlers.discord_handler import DiscordHandler
from .handlers.function_handler import FunctionHandler
from .handlers.usage_metrics import TERRA, model_label
from .handlers.vector_handler import EMBEDDING_MODEL
from .metrics import initialize_counters, initialize_model_counters, start_metrics_server
from .storage import Database
from .storage.discovery_shadow import DISCOVERY_TOOL_NAMES
from .storage.message_archive import MessageArchive
from .handlers.reaction_shadow import ReactionShadow

def run():
    asyncio.run(_main())

async def _main():
    logging.info("Initializing Discord bot")
    # Read in configurations and credentials
    DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
    OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
    PINECONE_API_KEY = os.environ['PINECONE_API_KEY']

    initialize_counters(FunctionHandler.load_functions(), DISCOVERY_TOOL_NAMES.values(),
                        youtube_tool=ReadYouTube.name)
    shared_model = os.getenv("OPENAI_MODEL", TERRA)
    reaction_model = os.getenv("REACTION_SHADOW_MODEL", shared_model)
    for operation, model in (
        ("reply", GPT_MODEL), ("reaction", reaction_model), ("discovery", shared_model),
        ("memory_extraction", shared_model), ("memory_evaluation", shared_model),
    ):
        initialize_model_counters(operation, model_label(model))
    for operation in ("reply_recall_embedding", "memory_evaluation_embedding",
                      "memory_publication_embedding"):
        initialize_model_counters(operation, model_label(EMBEDDING_MODEL), embeddings=True)

    runner = await start_metrics_server()
    try:
        await _run_bot(DISCORD_TOKEN, OPENAI_API_KEY, PINECONE_API_KEY)
    finally:
        await runner.cleanup()


async def _run_bot(discord_token, openai_api_key, pinecone_api_key):
    discord_bot = DiscordHandler(discord_token, openai_api_key, pinecone_api_key)

    # Opt-in until the persistent volume is mounted in each environment.
    # Never silently fall back to a database in the container filesystem.
    database = None
    try:
        database_path = os.getenv("DISCORD_SQLITE_PATH")
        if database_path:
            database = Database(database_path).open()
            database.integrity_check()
            logging.info("SQLite storage initialized")
            discord_bot.archive = MessageArchive(database)
            guild_id = os.getenv('REACTION_SHADOW_GUILD_ID')
            if guild_id:
                if not guild_id.isdecimal():
                    raise ValueError('REACTION_SHADOW_GUILD_ID must be numeric')
                discord_bot.reaction_shadow = ReactionShadow(
                    database.connection, guild_id=guild_id, api_key=openai_api_key,
                    discord_client=discord_bot.client)
                logging.info('Live reactions configured')
        await discord_bot.start()
    finally:
        try:
            await discord_bot.shutdown()
        finally:
            if database is not None:
                database.close()

