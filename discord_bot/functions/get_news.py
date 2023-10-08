from discord_bot.functions.base import BaseFunction
import os, json
from newsapi import NewsApiClient

class GetNews(BaseFunction):
    name = "get_news"
    description = "Fetches news articles based on given criteria. Can retrieve top headlines or a broader set of news articles."
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["top_headlines", "everything"],
                "description": "Specify whether to fetch top headlines or a broader set of news articles."
            },
            "keywords": {
                "type": "string",
                "description": "Keywords to search for in the news articles."
            },
            "category": {
                "type": "string",
                "description": "Category of news to fetch. Only applicable in 'top_headlines' mode."
            },
            "from_date": {
                "type": "string",
                "description": "Starting date for news articles in YYYY-MM-DD format. Only applicable in 'everything' mode."
            },
            "to_date": {
                "type": "string",
                "description": "Ending date for news articles in YYYY-MM-DD format. Only applicable in 'everything' mode."
            },
            "language": {
                "type": "string",
                "description": "Language of the news articles."
            },
            "country": {
                "type": "string",
                "description": "Country to fetch news from. Only applicable in 'top_headlines' mode."
            }
        },
        "required": ["mode","keywords"]
    }

    def __init__(self):
        self.news_api_key = os.environ.get('NEWS_API_KEY')
        self.api = NewsApiClient(api_key=self.news_api_key)


    async def execute(self, args):
        mode = args.get('mode')
        keywords = args.get('keywords', '')
        category = args.get('category', None)
        from_date = args.get('from_date', None)
        to_date = args.get('to_date', None)
        language = args.get('language', 'en')
        country = args.get('country', 'us')

        try:
            if mode == 'top_headlines':
                response = self.api.get_top_headlines(q=keywords, category=category, language=language, country=country, page_size=10)
            elif mode == 'everything':
                response = self.api.get_everything(q=keywords, from_param=from_date, to=to_date, language=language, sort_by='relevancy', page_size=10)
            else:
                return "Invalid mode specified."
            
            if response['status'] == 'ok':
                return json.dumps(response)
            else:
                return f"API returned an error: {response['status']}"
        except Exception as e:
            return f"An error occurred: {str(e)}"
