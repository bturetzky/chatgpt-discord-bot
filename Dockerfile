# Use an official Python runtime as a parent image
FROM python:3.8-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install Poetry
RUN pip install poetry

# Disable virtualenv creation by Poetry and install dependencies
RUN poetry config virtualenvs.create false
RUN poetry install --no-dev -vvv # Exclude development dependencies

# Run the bot script when the container launches
CMD ["python", "-m", "run.py"]
