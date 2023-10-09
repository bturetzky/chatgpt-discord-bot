from discord_bot.functions.base import BaseFunction
import os, aiohttp, json

class IGDBPlatformInfo(BaseFunction):
    name = "igdb_platform_info"
    description = (
        "Fetches platform information from the IGDB database. "
        "This function can be used to get platform IDs, names, and other details. "
        "The function uses the Apicalypse query language."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The Apicalypse query string to specify which platform details to fetch. "
                    "You can include the fields: 'id', 'name'(you should always include this), 'abbreviation', and 'generation'. "
                    "Note: Use only these fields in your query. "
                    "Example query: 'fields name, id; search \"xbox\";'"
                )
            }
        },
        "required": ["query"]
    }

    def __init__(self):
        self.client_id = os.getenv("IGDB_CLIENT_ID")
        self.client_secret = os.getenv("IGDB_CLIENT_SECRET")

    async def execute(self, args):
        async with aiohttp.ClientSession() as session:
            # Get the bearer token
            auth_url = 'https://id.twitch.tv/oauth2/token'
            auth_params = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials'
            }
            async with session.post(auth_url, params=auth_params) as auth_resp:
                if auth_resp.status != 200:
                    return f"Failed to get token: {await auth_resp.text()}"
                token_data = await auth_resp.json()
                token = token_data['access_token']

            # Prepare headers
            headers = {
                'Client-ID': self.client_id,
                'Authorization': f'Bearer {token}'
            }

            query = args.get('query')

            # Make the API call
            api_url = 'https://api.igdb.com/v4/platforms/'
            async with session.post(api_url, headers=headers, data=query) as response:
                if response.status == 200:
                    return json.dumps(await response.json())
                else:
                    return f"An error occurred: {await response.text()}"
