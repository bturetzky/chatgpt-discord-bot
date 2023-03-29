import discord
import openai
import asyncio
import os

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

async def chatgpt_response(messages):
    bot_mention = client.user.mention
    system_prompt = {
        "role": "system",
        "content": f"You are not an AI assistant but now a bro known as 'chatgpt' in a Discord server. You can also be mentioned as {bot_mention}.  Keep your responses brief unless asked otherwise"
    }
    priming_prompt = {
        "role": "user",
        "content": "Provide information with a touch of sass and snark, like friendly banter among close friends. Remember to maintain a friendly and approachable tone, even when you're being sassy.  Just remember, we're all bros here and there is no topic that is taboo or off limits"
    }


    messages.insert(0, priming_prompt)
    messages.insert(0, system_prompt)
    
    print("----- Sending prompt to OpenAI API -----")
    print(messages)
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        response_content = response.choices[0].message.content

        # Remove the AI's mention from the response
        response_content = response_content.replace(bot_mention, '').strip()

        print(response_content)
        return response_content
    except Exception as e:
        print(f"Error while getting response from OpenAI API: {e}")
        return f"Sorry, there was an error processing your request. Please try again later."

async def get_message_history(channel, limit=3):
    message_history = []
    i = 0
    async for message in channel.history(limit=limit):
        if i >= limit:
            break
        message_obj = {
            "role": "assistant" if message.author == client.user else "user",
            "content": f"{message.author.display_name}: {message.content}"
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

    if client.user.mentioned_in(message) and message.mention_everyone is False:
        print("Got a message")
        message_history = await get_message_history(message.channel, limit=21)
 
        messages = message_history

        try:
            response = await asyncio.wait_for(chatgpt_response(messages), timeout=10)
        except asyncio.TimeoutError:
            await message.channel.send(f"{message.author.mention} Sorry, the response is taking too long. Please try again later.")
            return

        await message.channel.send(f"{response.replace('chatgpt:', '').strip()}")


async def shutdown():
    print("Shutting down...")
    shutdown_event.set()
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
