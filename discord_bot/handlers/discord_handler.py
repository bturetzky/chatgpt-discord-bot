import discord, asyncio
from .chatgpt_handler import ChatGPTHandler
from .vector_handler import VectorHandler

class DiscordHandler:
    def __init__(self, discord_token, openai_key, pinecone_apikey):
        self.token = discord_token
        self.client = discord.Client(intents=self.get_discord_intents())
        self.chatgpt_handler = ChatGPTHandler(openai_key, self.send_interim_message)
        self.vector_handler = VectorHandler(openai_key, pinecone_apikey) 
        self.shutdown_event = asyncio.Event()
        
        # Register Discord event callbacks
        @self.client.event
        async def on_ready():
            print(f'{self.client.user} has connected to Discord!')
        
        @self.client.event
        async def on_message(message):
            await self.process_message(message)
    
    async def start(self):
        # This will start the Discord client and run until it's disconnected
        await self.client.start(self.token)
    
    async def send_interim_message(self, channel, interim_message):
        # Logic to send an interim message to Discord
        try:
            # Send the ACTUAL message...            
            await channel.send(interim_message)
        except Exception as e:
            print(f"Error occurred while processing the message: {e}")
            # Don't send an error on a short message
        return

    async def shutdown(self):
        # Close any resources, db connections, etc.
        print("Shutting down...")
        self.shutdown_event.set()
        await self.vector_store.close()
        await self.client.close()

    def get_discord_intents(self, messages=True, guilds=True):
        intents = discord.Intents.default()
        intents.messages = messages
        intents.guilds = guilds
        return intents

    async def process_message(self, message):
        # Logic to process the message, interact with ChatGPTHandler, etc.
        if message.author == self.client.user or self.shutdown_event.is_set():
            if message.author == self.client.user:
                print("Suppressing embeds?")
                await message.edit(suppress=True)  # Suppress the bot's message
                # Why does this only work sometimes even if the bot has the right permissions?
            return
        
        channel = message.channel

        # Hacky way to get the bot's mention
        if self.chatgpt_handler.bot_mention is None:
            self.chatgpt_handler.bot_mention = self.client.user.mention
        
        if self.client.user.mentioned_in(message) and message.mention_everyone is False or message.guild is None:
            # Do all the work here
            print(f"Got a message from {message.author.display_name}: {message.content}")
            author_id = str(message.author.id)  # Get the author's ID
            # Tweak the limit here to get more or less context
            try:
                messages = await self.get_message_history(channel, limit=7)
            except Exception as e:
                print(f"Error while getting message history: {e}")
            guild_id = str(message.guild.id) if message.guild else "DM"

            print("Getting memories...")
            memories = self.vector_handler.get_relevant_contexts(message.content, author_id)  # Get the relevant contexts from the vector store
            for memory in memories:
                messages.insert(0, {
                    "role": "system",
                    "content": f"Memory: {memory}"
                })
            print(f"Got memories: {memories}")

            try:
                response = await self.chatgpt_handler.get_response(messages, channel)
            except Exception as e:
                print(f"Error occurred while processing the message: {e}")
                await message.channel.send(
                    f"{message.author.display_name} Sorry, there was an error processing your request. Please try again later."
                )
                return
            split_response = self.split_message(response.replace("chatgpt:", "").strip())
            try:
                # Send the ACTUAL message...            
                for message_part in split_response:
                    await message.channel.send(message_part)
                    await asyncio.sleep(1)  # Add a 1-second delay between messages
            except Exception as e:
                print(f"Error occurred while processing the message: {e}")
                await message.channel.send(
                    f"{message.author.display_name} Sorry, there was an error with sending the message itself. Please try again later."
                )
                return

            try:
                summary = await self.chatgpt_handler.get_summary(messages)
            except Exception as e:
                print(f"Error occurred while summarizing the messages: {e}")
                return
            
            self.vector_handler.store_additional_data(summary.content, author_id)  # Update the vector store with the summary
            
    async def get_message_history(self, channel, limit=3):
        message_history = []
        i = 0
        print(f"Getting message history for {channel}")
        async for message in channel.history(limit=limit):
            if i >= limit:
                break
            message_obj = {
                "role": "assistant" if message.author == self.client.user else "user",
                "content": f"{message.author.mention}: {message.content}"
            }
            message_history.append(message_obj)
            i += 1

        # Reverse the order to maintain the correct chronological order
        message_history.reverse()

        return message_history
        
    def split_message(self, message):
        # Logic to split the message into multiple messages if needed
        #TODO: Implement this
        return [message]
