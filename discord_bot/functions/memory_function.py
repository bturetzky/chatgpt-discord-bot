from discord_bot.functions.base import BaseFunction
from discord_bot.handlers.vector_handler import VectorHandler

class WeatherLookup(BaseFunction):
    name = "store_memory"
    description = "This function is your go-to for storing the good stuff. Use it to save key details or insights that you'll need for future interactions. This is especially important for understanding individual users and their preferences. Think of it as building your personal cheat sheet for each user."
    parameters = {
        "type": "object",
        "properties": {
            "memory": {
                "type": "string",
                "description": "Here's where you jot down what you want to remember. Make it concise but info-packed. This is your chance to store things like user preferences, important dates, or any other tidbits that'll help you be more personalized and helpful in the future."
            }
        },
        "required": ["memory"]
    }

    def __init__(self):
        self.vector_handler = VectorHandler()

    async def execute(self, args):
        self.vector_handler.store_additional_data(args['memory'])
        return "Memory stored."