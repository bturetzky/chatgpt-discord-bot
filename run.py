from discord_bot import app
import logging

if __name__ == "__main__":
    logging.basicConfig(level=getattr(logging, __import__("os").getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
    logging.info("Starting up")
    app.run()
