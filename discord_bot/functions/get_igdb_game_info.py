from discord_bot.functions.base import BaseFunction
import os, aiohttp, json

class IGDBGameInfo(BaseFunction):
    name = "igdb_game_info"
    description = (
        "Fetches detailed information about video games from the IGDB database. "
        "This function can be used to get various details like game name, genres, "
        "release dates, and more. The function uses the Apicalypse query language. "
        "Make sure to use only the fields provided in the description."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The Apicalypse query string to specify which game details to fetch. "
                    "You can include the fields: 'name', 'id'(IGDB's internal ID of the game, don't guess at these), 'genres', "
                    "'platforms' (Array of Platform IDs, look these up first, don't guess), 'first_release_date' (unix timestamp format; "
                    "please convert this to a human-readable date format like 'MM-DD-YYYY' when reporting to the user), 'similar_games' (array of game IDs), "
                    "'total_rating' (an average rating based on various sources), "
                    "'summary', 'status' (game release status: 0 for released, 2 for alpha, 3 for beta, 4 for early_access, "
                    "5 for offline, 6 for cancelled, 7 for rumored, 8 for delisted -- Don't rely on all games to have this field set), "
                    "'player_perspectives' (player perspectives like first-person, third-person, etc.), "
                    "and 'multiplayer_modes' (types of multiplayer modes available). "
                    "Note: Use only these fields in your query. "
                    "Example query: 'fields name, genres.name, total_rating, summary; where genres.name = \"Role-playing (RPG)\" & total_rating >= 80; sort aggregated_rating desc; limit 5;'"
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
            api_url = 'https://api.igdb.com/v4/games/'
            async with session.post(api_url, headers=headers, data=query) as response:
                if response.status == 200:
                    return json.dumps(await response.json())
                else:
                    return f"An error occurred: {await response.text()}"

