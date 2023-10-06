from .function_handler import FunctionHandler
import discord_bot.handlers.utilities as utilities, openai, json, asyncio
from openai.error import OpenAIError
from requests.exceptions import RequestException

class ChatGPTHandler:
    def __init__(self, openai_apikey, send_interim_message_callback=None):
        self.bot_mention = None
        openai.api_key = openai_apikey
        self.send_interim_message = send_interim_message_callback
        self.function_handler = FunctionHandler()
        
    async def get_response(self, messages, context):
        # 1. Pass messages to OpenAI API
        # 2. If a function needs to be executed:
        #    a. Call self.send_interim_message if provided
        #    b. Call self.function_handler.process_functions()
        # 3. Return the response to DiscordHandler

        system_prompt = {
            "role":
            "system",
            "content": utilities.get_response_system_prompt_content(self.bot_mention)
        }
        priming_prompt = {
            "role":
            "user",
            "content": utilities.get_response_priming_prompt_content(self.bot_mention)
        }

        # Fetch the context here
        #TODO: Implement the vector store

        # Supposed to be better at not needing the priming prompt, lets just try it with the system prompt only
        #messages.insert(0, priming_prompt)
        messages.insert(0, system_prompt)

        MAX_FUNCTION_CALLS = 3

        try:
            function_calls_count = 0
            while True:  # Start a loop to keep asking the model until we get a non-function reply
                print("----- Sending prompt to OpenAI API -----")
                print(messages)

                if function_calls_count >= MAX_FUNCTION_CALLS:
                    force_final_response = {"function_call": None}
                else:
                    force_final_response = {"function_call": "auto"}
                response = openai.ChatCompletion.create(model="gpt-4",
                                                        messages=messages, 
                                                        functions=self.function_handler.api_functions,
                                                        **force_final_response)
                response_content = response.choices[0].message

                print(f"response_content: {response_content}")

                if response_content.get("function_call"):
                    function_calls_count += 1  # Increment the counter
                    function_name = response_content["function_call"]["name"]
                    function_args = json.loads(response_content["function_call"]["arguments"])
                    
                    # Call the function handler to execute the function
                    function_response = await self.function_handler.execute_function(function_name, function_args)

                    if response_content.get("content") is not None:
                        self.send_interim_message(response_content["content"])  # Send the interim message to the user
                        response_content["content"] = None  # Remove the content from the response
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
