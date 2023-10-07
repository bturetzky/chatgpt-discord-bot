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
            "content": utilities.get_response_system_prompt_content(self.bot_mention)
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
                response = openai.ChatCompletion.create(model="gpt-4",
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

        
