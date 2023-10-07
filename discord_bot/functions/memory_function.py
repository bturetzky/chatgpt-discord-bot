from discord_bot.functions.base import BaseFunction
from discord_bot.handlers.vector_handler import VectorHandler

class WeatherLookup(BaseFunction):
    name = "store_memory"
    description = "Stores important or information-rich details into memories. Use this function to save key details or insights that should be remembered for future interactions."
    parameters = {
        "type": "object",
        "properties": {
            "memory": {
                "type": "string",
                "description": "The specific memory to store. This should be a concise yet detailed summary of important information or insights that would be beneficial for future interactions."
            }
        },
        "required": ["memory"]
    }

    def __init__(self):
        self.vector_handler = VectorHandler()

    async def execute(self, args):
        self.vector_handler.store_additional_data(args['memory'])
        return "Memory stored."