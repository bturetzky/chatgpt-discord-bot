# Use an official Python runtime as a parent image
FROM python:3.10-slim

LABEL org.opencontainers.image.source=https://github.com/bturetzky/chatgpt-discord-bot
LABEL org.opencontainers.image.description="ChatGPT powered Discord bot"
LABEL org.opencontainers.image.licenses=MIT

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for lxml
RUN apt-get update \
    && apt-get install -y libxml2-dev libxslt1-dev \
    && apt-get clean

# Set the working directory in the container
WORKDIR /app

# Install the same Poetry version used to generate poetry.lock.
RUN pip install --no-cache-dir 'poetry==1.8.3'

# Dependency installation is cached until pyproject.toml or poetry.lock changes.
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-root --no-interaction

# Copy application code only after dependencies are installed.
COPY . /app

# Catch syntax/import failures and run focused tests before publishing an image.
RUN python -m compileall -q discord_bot run.py \
    && python -m unittest discover -s tests -t .

# Run the bot script when the container launches
CMD ["python", "-m", "run"]
