from datetime import datetime
from .function_handler import FunctionHandler
import openai, json, asyncio
from openai.error import OpenAIError
from requests.exceptions import RequestException

# The model to use for the chatbot
GPT_MODEL = "gpt-4"  # This model gets rate limited so hard
#GPT_MODEL = "gpt-3.5-turbo-0613"  # This model has a small context window so not much works

class ChatGPTHandler:
    def __init__(self, openai_apikey, send_interim_message_callback=None):
        self.bot_mention = None
        openai.api_key = openai_apikey
        self.send_interim_message = send_interim_message_callback
        self.function_handler = FunctionHandler()

    def get_response_system_prompt_content(self, bot_mention):
        current_date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        knowledge_cutoff = "2021-09-01"
        prompt_statements = [
            f"Yo, you're {bot_mention}, the snazzy bro-bot in this Discord server.",
            "Remember, you're among friends here, so keep it real, keep it sassy, and don't hold back.",
            f"Today's date and time is {current_date_time}, but keep in mind my training data only goes up until {knowledge_cutoff}.",
            "You've got a bunch of cool functions at your disposal. Use them to make life easier for everyone here. That includes searching the web, fetching content, and more."
            "Don't forget to store important memories, especially stuff that helps you get to know the peeps around here better.",
            "If something's unclear, just ask. Go wild!"
        ]

        prompt = " ".join(prompt_statements)
        return prompt

        
    async def get_response(self, messages, channel):
        # 1. Pass messages to OpenAI API
        # 2. If a function needs to be executed:
        #    a. Call self.send_interim_message if provided
        #    b. Call self.function_handler.process_functions()
        # 3. Return the response to DiscordHandler
        # 4. Update the vector store with the response and context
        # 5. Repeat from step 1

        system_prompt = {
            "role": "system",
            "content": self.get_response_system_prompt_content(self.bot_mention)
        }

        messages.insert(0, system_prompt)

        MAX_FUNCTION_CALLS = 7  # Maximum number of function calls to make before giving up

        try:
            function_calls_count = 0
            while True:  # Start a loop to keep asking the model until we get a non-function reply
                print("----- Sending prompt to OpenAI API -----")
                # True debug spam
                print(messages)

                if function_calls_count >= MAX_FUNCTION_CALLS:
                    force_final_response = {"function_call": None}
                else:
                    force_final_response = {"function_call": "auto"}
                response = openai.ChatCompletion.create(model=GPT_MODEL,
                                                        messages=messages, 
                                                        functions=self.function_handler.api_functions,
                                                        **force_final_response)
                response_content = response.choices[0].message
                await asyncio.sleep(3)  # Add a 1-second delay between messages

                print(f"response_content: {response_content}")

                if response_content.get("function_call"):
                    function_calls_count += 1  # Increment the counter
                    function_name = response_content["function_call"]["name"]
                    function_args = json.loads(response_content["function_call"]["arguments"])
                    
                    # Call the function handler to execute the function
                    function_response = await self.function_handler.execute_function(function_name, function_args)

                    # If there is content send an interim message to the user
                    if response_content.get("content") is not None:
                        await self.send_interim_message(channel, response_content["content"])  # Send the interim message to the user
                        response_content["content"] = None  # Remove the content from the response
                    if function_args.get("quick_update") is not None: 
                        await self.send_interim_message(channel, function_args["quick_update"]) # Send the interim message to the user

                    # Send the info on the function call and function response to GPT
                    messages.append(response_content)  # extend conversation with assistant's reply
                    messages.append(
                        {
                            "role": "function",
                            "name": function_name,
                            "content": function_response,
                        }
                    )  # extend conversation with function response
                    
                    # Go back to the start of the loop and ask the model again.
                    
                    continue
                else:
                    reply = response_content["content"]
                    messages.append(response_content)
                    # Remove the AI's mention from the response
                    reply = reply.replace(f"{self.bot_mention}: ", '').strip()
                    print(reply)
                    return reply

        except OpenAIError as e:
            print(f"Error from OpenAI: {e}")
            return "Sorry, there was an error processing your request with OpenAI. Please try again later."
        except RequestException as e:
            print(f"Network error: {e}")
            return "Sorry, there was a network error. Please try again later."
        except asyncio.TimeoutError:
            return "Sorry, the request took too long. Please try again later."
        
    #TODO: Remove this if the memory function works out
    async def get_summary(self, messages):
        messages.append({
            "role": "system",
            "content": utilities.get_summary_prompt_content(self.bot_mention)
        })
        try:
            summary_response = openai.ChatCompletion.create(model="gpt-4",
                                                messages=messages)
            await asyncio.sleep(3)  # Add a 1-second delay between messages
        except OpenAIError as e:
            print(f"Error from OpenAI: {e}")
            return "Sorry, there was an error processing your request with OpenAI. Please try again later."
        except RequestException as e:
            print(f"Network error: {e}")
            return "Sorry, there was a network error. Please try again later."
        summary = summary_response.choices[0].message
        #print(f"Summary: {summary}")
        print("Got summary from OpenAI API...")
        return summary

        
