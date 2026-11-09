import discord, asyncio, logging, os, re
from .chatgpt_handler import ChatGPTHandler
from .vector_handler import VectorHandler
from .image_context import ImageContextBuilder
from ..storage.history import reconcile_recent
from ..storage.reaction_observer import ReactionObserver

CONTEXT_LIMIT = int(os.getenv("DISCORD_CONTEXT_LIMIT", "30"))
RELATIONSHIP_MEMORY_LIMIT = int(os.getenv("RELATIONSHIP_MEMORY_LIMIT", "4"))

class DiscordHandler:
    def __init__(self, discord_token, openai_key, pinecone_apikey, archive=None):
        self.token = discord_token
        self.archive = archive
        self._reconcile_task = None
        logging.debug('Initializing discord client')
        self.client = discord.Client(intents=self.get_discord_intents())
        logging.debug('Discord client initialized')
        # Initialize the vector handler before chatgpt_handler
        logging.debug('Initiazliaing Vector store')
        self.vector_handler = VectorHandler(openai_key, pinecone_apikey)
        logging.debug('Vector store initialized')
        logging.debug('Initiazliaing ChatGPT client')
        self.chatgpt_handler = ChatGPTHandler(openai_key, self.send_interim_message)
        logging.debug('ChatGPT client initialized')
        self.shutdown_event = asyncio.Event()
        self.image_context_builder = ImageContextBuilder()
        
        # Register Discord event callbacks
        @self.client.event
        async def on_ready():
            logging.info('Discord gateway ready: bot_id=%s guilds=%d message_content_intent=%s', self.client.user.id, len(self.client.guilds), self.client.intents.message_content)
            if self.archive is not None and self._reconcile_task is None:
                self._reconcile_task = asyncio.create_task(
                    reconcile_recent(self.client, self.archive), name='discord-history-reconcile'
                )
        
        @self.client.event
        async def on_message(message):
            logging.debug('Discord message received: guild=%s is_dm=%s mentioned=%s content_available=%s',
                         getattr(message.guild, 'id', None), message.guild is None,
                         self.client.user.mentioned_in(message) if self.client.user else False,
                         bool(message.content))
            if self.archive is not None and message.guild is not None:
                try:
                    self.archive.upsert(message)
                except Exception:
                    logging.exception('Discord message archive write failed')
            await self.process_message(message)

        @self.client.event
        async def on_raw_reaction_add(payload):
            if self.archive is None or self.client.user is None:
                return
            try:
                # Member may be absent on uncached events; never classify bot reactions as human.
                if payload.member is None or payload.member.bot:
                    return
                ReactionObserver(self.archive.db).add(payload, bot_user_id=self.client.user.id)
            except Exception:
                logging.exception("Reaction observation add failed")

        @self.client.event
        async def on_raw_reaction_remove(payload):
            if self.archive is None:
                return
            try:
                ReactionObserver(self.archive.db).remove(payload)
            except Exception:
                logging.exception("Reaction observation remove failed")

        @self.client.event
        async def on_raw_reaction_clear(payload):
            if self.archive is None:
                return
            try:
                ReactionObserver(self.archive.db).clear(payload)
            except Exception:
                logging.exception("Reaction observation clear failed")

        @self.client.event
        async def on_raw_reaction_clear_emoji(payload):
            if self.archive is None:
                return
            try:
                ReactionObserver(self.archive.db).clear_emoji(payload)
            except Exception:
                logging.exception("Reaction observation emoji clear failed")

        @self.client.event
        async def on_raw_message_edit(payload):
            if self.archive is None or payload.guild_id is None:
                return
            # Partial raw edits have no complete content; never overwrite with empty text.
            if 'content' not in payload.data:
                return
            try:
                self.archive.edit(str(payload.message_id), payload.data['content'], payload.data.get('edited_timestamp'))
                # Recover edits for messages not yet indexed (e.g. after downtime).
                if not self.archive.db.execute(
                    'SELECT 1 FROM messages WHERE message_id=?', (str(payload.message_id),)
                ).fetchone():
                    channel = self.client.get_channel(payload.channel_id)
                    if channel is not None and hasattr(channel, 'fetch_message'):
                        try:
                            self.archive.upsert(await channel.fetch_message(payload.message_id))
                        except (discord.NotFound, discord.Forbidden):
                            logging.debug('Edited message unavailable for archive recovery')
            except Exception:
                logging.exception('Discord message archive edit failed')

        @self.client.event
        async def on_raw_message_delete(payload):
            if self.archive is not None and payload.guild_id is not None:
                try:
                    self.archive.delete(payload.message_id)
                    ReactionObserver(self.archive.db).clear(payload)
                except Exception:
                    logging.exception('Discord message archive deletion failed')

        @self.client.event
        async def on_raw_bulk_message_delete(payload):
            if self.archive is not None and payload.guild_id is not None:
                try:
                    for message_id in payload.message_ids:
                        self.archive.delete(message_id)
                        self.archive.db.execute(
                            'DELETE FROM reaction_members WHERE message_id=?', (str(message_id),))
                except Exception:
                    logging.exception('Discord bulk archive deletion failed')

        @self.client.event
        async def on_disconnect():
            logging.warning('Discord gateway disconnected')

        @self.client.event
        async def on_resumed():
            logging.info('Discord gateway session resumed')
    
    async def start(self):
        # This will start the Discord client and run until it's disconnected
        await self.client.start(self.token)
    
    async def send_interim_message(self, channel, interim_message):
        # Logic to send an interim message to Discord
        try:
            # Send the ACTUAL message...            
            await channel.send(interim_message)
        except Exception:
            logging.exception('Discord interim message send failed')
            # Don't send an error on a short message
        return

    async def shutdown(self):
        # Close any resources, db connections, etc.
        logging.info('Shutting down Discord client')
        self.shutdown_event.set()
        reconcile_task = getattr(self, '_reconcile_task', None)
        if reconcile_task is not None:
            reconcile_task.cancel()
            await asyncio.gather(reconcile_task, return_exceptions=True)
        try:
            await self.client.close()
        finally:
            await self.vector_handler.close()

    def get_discord_intents(self, messages=True, guilds=True):
        intents = discord.Intents.default()
        intents.messages = messages
        intents.guilds = guilds
        intents.message_content = True
        intents.reactions = True
        return intents

    async def process_message(self, message):
        # Logic to process the message, interact with ChatGPTHandler, etc.
        if message.author == self.client.user or self.shutdown_event.is_set():
            if message.author == self.client.user:
                logging.debug('Suppressing bot message embeds')
                await asyncio.sleep(5)  # Add a delay before suppressing the embeds or it won't work
                await message.edit(suppress=True)  # Suppress the bot's message
            return
        
        channel = message.channel

        # Hacky way to get the bot's mention
        if self.chatgpt_handler.bot_mention is None:
            self.chatgpt_handler.bot_mention = self.client.user.mention
        
        if self.client.user.mentioned_in(message) and message.mention_everyone is False or message.guild is None:
            # Do all the work here
            logging.info('Processing Discord message: guild=%s author_id=%s', getattr(message.guild, 'id', None), message.author.id)
            author_id = str(message.author.id)  # Get the author's ID
            # Tweak the limit here to get more or less context
            try:
                messages = await self.get_message_history(channel, limit=CONTEXT_LIMIT)
            except Exception:
                logging.exception("Unable to retrieve Discord history; using current message")
                messages = [{"role": "user", "content": f"{message.author.display_name} (Discord ID {message.author.id}): {message.content}"}]

            logging.debug('Retrieving memories')
            memory_query = self.build_memory_query(messages)
            participant_ids = [author_id]
            for item in reversed(messages):
                if item.get("role") != "user":
                    continue
                for match in re.findall(r"Discord ID (\d+)", item.get("content", "")):
                    if match not in participant_ids and len(participant_ids) < 3:
                        participant_ids.append(match)
            try:
                memories = await asyncio.to_thread(
                    self.vector_handler.get_relevant_contexts, memory_query
                ) or []
            except Exception:
                logging.exception("Semantic memory lookup failed; continuing")
                memories = []
            try:
                relationships = await asyncio.to_thread(
                    self.vector_handler.get_relationship_contexts,
                    participant_ids, RELATIONSHIP_MEMORY_LIMIT
                ) or []
            except Exception:
                logging.exception("Relationship memory lookup failed; continuing")
                relationships = []
            # A retrieval adapter must return a concrete list of memory text.
            # Ignore malformed responses rather than corrupting the chat context.
            memories = memories if isinstance(memories, list) else []
            relationships = relationships if isinstance(relationships, list) else []
            unique_memories = list(dict.fromkeys(
                item for item in relationships + memories if isinstance(item, str) and item.strip()
            ))
            for memory in reversed(unique_memories):
                messages.insert(0, {"role": "system", "content": f"Memory (possibly outdated): {memory}"})
            logging.info(
                'Memory retrieval completed: semantic=%d relationship=%d unique=%d',
                len(memories), len(relationships), len(unique_memories)
            )

            if getattr(message, "attachments", None) or getattr(message, "reference", None):
                try:
                    image_context = await self.image_context_builder.build(message)
                    if image_context:
                        messages.append(image_context)
                except Exception as exc:
                    logging.warning("Image ingestion failed: category=internal_error error_type=%s", type(exc).__name__)
                    messages.append({"role": "user", "content": [{"type": "input_text", "text": "Attached image processing failed. Do not claim to have seen the images."}]})

            try:
                response = await self.chatgpt_handler.get_response(
                    messages, channel, discord_context={
                        'archive': getattr(self, 'archive', None), 'guild': message.guild, 'member': message.author, 'channel_id': str(message.channel.id)
                    })
            except Exception:
                logging.exception('Discord message processing failed')

                await message.channel.send(
                    f"{message.author.display_name} Sorry, there was an error processing your request. Please try again later."
                )
                return
            split_response = self.split_message(response.replace("chatgpt:", "").strip())
            try:
                # Send the ACTUAL message...            
                for message_part in split_response:
                    await message.channel.send(message_part)
                    await asyncio.sleep(3)  # Add a 3-second delay between messages
            except Exception:
                logging.exception('Discord message send failed')
                await message.channel.send(
                    f"{message.author.display_name} Sorry, there was an error with sending the message itself. Please try again later."
                )
                return

            # Skipping this in lieu of memory function
            #try:
            #    summary = await self.chatgpt_handler.get_summary(messages)
            #except Exception as e:
            #    print(f"Error occurred while summarizing the messages: {e}")
            #    return
            #
            #self.vector_handler.store_additional_data(summary.content, author_id)  # Update the vector store with the summary
            
    @staticmethod
    def build_memory_query(messages, max_turns=6, max_chars=2400):
        """Bounded, speaker-attributed user turns for semantic retrieval."""
        turns = [
            item["content"]
            for item in messages
            if item.get("role") == "user" and isinstance(item.get("content"), str)
            and item["content"].strip()
        ]
        selected = []
        remaining = max_chars
        for turn in reversed(turns):
            if len(selected) >= max_turns or remaining <= 0:
                break
            excerpt = turn[:remaining]
            selected.append(excerpt)
            remaining -= len(excerpt)
        return "\n".join(reversed(selected))

    async def get_message_history(self, channel, limit=3):
        message_history = []
        i = 0
        logging.debug('Retrieving Discord message history')
        async for message in channel.history(limit=limit):
            if i >= limit:
                break
            message_obj = {
                "role": "assistant" if message.author == self.client.user else "user",
                "content": (f"{message.author.display_name} (Discord ID {message.author.id}): {message.content}"
                            if message.author != self.client.user else f"{message.author.mention}: {message.content}")
            }
            message_history.append(message_obj)
            i += 1

        # Reverse the order to maintain the correct chronological order
        message_history.reverse()

        return message_history
        
    def split_message(self, message, limit=1950):
        # Logic to split the message into multiple messages if needed
        chunks = []
        current_chunk = ""
        in_code_block = False
        lines = message.split('\n')
        
        for line in lines:
            # Detect code block start or end
            if line.startswith("```"):
                in_code_block = not in_code_block
            
            # Check if adding the new line would exceed the limit
            if len(current_chunk) + len(line) + 1 > limit:
                # If it does and we're not in a code block, add the current chunk to the list and start a new one
                if not in_code_block:
                    chunks.append(current_chunk)
                    current_chunk = ""
                else:
                    # If we're in a code block, add a warning and close the code block
                    current_chunk += "\n```"
                    chunks.append(current_chunk)
                    current_chunk = "```"  # Start a new code block in the next chunk
            
            # Add the line to the current chunk
            current_chunk += line + "\n"
        
        # Add the last chunk
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
