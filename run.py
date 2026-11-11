import logging
import os
import time

from discord_bot import app


def configure_logging():
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


if __name__ == "__main__":
    configure_logging()
    logging.info("Starting up")
    app.run()
