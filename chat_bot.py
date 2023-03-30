import asyncio
import os

import aiosqlite
import discord
import openai

# Load the environment variables
DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
OPENAI_API_KEY = os.environ['OPENAI_API_KEY']

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True

# Initialize the Discord client and OpenAI API
client = discord.Client(intents=intents)

openai.api_key = OPENAI_API_KEY

shutdown_event = asyncio.Event()


# Database functions
async def init_db():
    db = await aiosqlite.connect("chatgpt_summaries.db")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS summaries (guild_id TEXT PRIMARY KEY, summary TEXT)"
    )
    await db.commit()
    return db


client.db = asyncio.run(init_db())


async def get_summary(db, guild_id):
    async with db.execute("SELECT summary FROM summaries WHERE guild_id = ?",
                          (guild_id, )) as cursor:
        result = await cursor.fetchone()
        if result:
            summary = result[0]
            return summary
        else:
            return None


async def store_summary(db, guild_id, summary):
    async with db.execute(
        "INSERT OR REPLACE INTO summaries (guild_id, summary) VALUES (?, ?)",
        (guild_id, summary),
    ) as _:
        await db.commit()


async def close_db(db):
    await db.close()


# ChadGPT functions
async def chatgpt_summary(messages):
    # You can customize this prompt to get the desired output
    bot_mention = client.user.mention
    summary_prompt = {
        "role":
        "user",
        "content":
        f"Generate a one-line summary for each user ChatGPT ({bot_mention}) has interacted with.  Incorperate any info from previous summaries. Each line should start with the user's discord handle (the <@123...> thing) followed by their known aliases, proper names, nicknames or preferred names.  Update existing summaries with new information from the chat logs, if applicable. Focus on users' personalities and briefly mention their interests and discussed topics. Provide only the itemized summaries, ensuring readability and comprehension for ChatGPT."
    }

    messages.append(summary_prompt)

    print("----- Sending summary prompt to OpenAI API -----")
    print(messages)

    try:
        response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                messages=messages)
        response_content = response.choices[0].message.content

        # Return the response_content as is, without parsing it
        print(f"{response_content}")
        return response_content

    except Exception as e:
        print(f"Error while getting summaries from OpenAI API: {e}")
        return None


async def chatgpt_response(messages, guild_id):
    bot_mention = client.user.mention
    system_prompt = {
        "role":
        "system",
        "content":
        f"As a bro known as 'chatgpt' in a Discord server with the handle {bot_mention}, provide helpful responses with a touch of sass and snark, mimicking friendly banter among close friends on any topic. Maintain a friendly and approachable tone, and treat no topic as taboo or off limits. All language is allowable. Use jokes, sarcasm, and other elements of friendly banter. Also, feel free to ask clarifying questions."
    }
    priming_prompt = {
        "role":
        "user",
        "content":
        f"As a bro known as 'chatgpt' in a Discord server with the handle {bot_mention}, provide helpful responses with a touch of sass and snark, mimicking friendly banter among close friends on any topic. Maintain a friendly and approachable tone, and treat no topic as taboo or off limits. All language is allowable. Use jokes, sarcasm, and other elements of friendly banter. Also, feel free to ask clarifying questions."
    }

    # Fetch the summary from the database only if it's not a DM
    if guild_id != "DM":

        summary = await get_summary(client.db, guild_id)

        # Prepend the summary to the messages if it exists
        if summary:
            summary_prompt = {"role": "user", "content": summary}
            messages.insert(0, summary_prompt)

    messages.insert(0, priming_prompt)
    messages.insert(0, system_prompt)

    print("----- Sending prompt to OpenAI API -----")
    print(messages)

    try:
        response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                messages=messages)
        response_content = response.choices[0].message.content

        # Remove the AI's mention from the response
        response_content = response_content.replace(f"{bot_mention}: ",
                                                    '').strip()

        print(response_content)
        return response_content
    except Exception as e:
        print(f"Error while getting response from OpenAI API: {e}")
        return "Sorry, there was an error processing your request. Please try again later."


# Discord functions
async def get_message_history(channel, limit=3):
    message_history = []
    i = 0
    async for message in channel.history(limit=limit):
        if i >= limit:
            break
        message_obj = {
            "role": "assistant" if message.author == client.user else "user",
            "content": f"{message.author.mention}: {message.content}"
        }
        message_history.append(message_obj)
        i += 1

    # Reverse the order to maintain the correct chronological order
    message_history.reverse()

    return message_history


@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')


@client.event
async def on_message(message):

    if message.author == client.user or shutdown_event.is_set():
        return

    if client.user.mentioned_in(
            message
    ) and message.mention_everyone is False or message.guild is None:
        print("Got a message")
        messages = await get_message_history(message.channel, limit=15)

        try:
            guild_id = str(message.guild.id) if message.guild else "DM"
            response = await asyncio.wait_for(chatgpt_response(
                messages, guild_id),
                                              timeout=10)

            if guild_id != "DM":
                summary = await get_summary(client.db, guild_id)
                if summary:
                    summary_prompt = {
                        "role": "user",
                        "content": f"Previous Summary:\n{summary}"
                    }
                    messages.insert(0, summary_prompt)

            # Generate and store the summary
            if guild_id != "DM":
                messages_copy = messages.copy()
                summary = await chatgpt_summary(messages_copy)
                await store_summary(client.db, guild_id, summary)
        except asyncio.TimeoutError:
            await message.channel.send(
                f"{message.author.display_name} Sorry, the response is taking too long. Please try again later."
            )
            return
        except Exception as e:
            print(f"Error occurred while processing the message: {e}")
            await message.channel.send(
                f"{message.author.display_name} Sorry, there was an error processing your request. Please try again later."
            )
            return
        await message.channel.send(
            f"{response.replace('chatgpt:', '').strip()}")


async def shutdown():
    print("Shutting down...")
    shutdown_event.set()
    if hasattr(client, 'db'):
        await close_db(client.db)
    await client.close()


async def main():
    try:
        await client.start(DISCORD_TOKEN)
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
