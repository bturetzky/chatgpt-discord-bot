from .base import BaseFunction
from duckduckgo_search import AsyncDDGS
import logging

DDGS_DEFAULT_MAX_RESULTS = 1

class SearchWeb(BaseFunction):
    name = "search_web"
    description = ("Performs a web search using DuckDuckGo to retrieve a list of relevant webpages. Use this function only when encountering queries about recent events or topics beyond the knowledge cut-off date. Prioritize using existing knowledge for general information and rely on this search function specifically for up-to-date details or to verify information that may have changed recently. For in-depth research or multiple perspectives on a current event, you can follow up by using 'get_webpage_contents' to explore the links in more detail.")
    parameters = {
                    "type": "object", 
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to execute. Be as specific as possible to get the most relevant results."
                            },
                            
                        "max_results": {
                            "type": "number",
                            "description": "The maximum number of search results to return. Default is 1, but consider increasing for broader topics."
                            }
                        },
                    "required": ["query"]
                    }

    async def execute(self, args):
        query = args.get("query")
        max_results = args.get("max_results", DDGS_DEFAULT_MAX_RESULTS)
        if not query:
            return "No search query provided."

        #TODO: switch to using a logger instead of this nonsense
        print(f"Searching the web for: {query}")
        try:
            async with AsyncDDGS() as ddgs:
                results = ddgs.text(query, max_results=max_results)
                logging.debug(f"Raw results: {results}")
        except Exception as e:
            print(f"Error occurred while searching the web: {e}")
            return "An error occurred while searching the web."
        
        # Format the results for a more readable output (if needed)
        # For now, I'm just joining them with line breaks:
        # Extract titles and links and format
        formatted_results = [f"{result['title']} - {result['href']}" for result in results]


        # Join them together
        reply = "\n".join(formatted_results)
        print(f"Search results: {reply}")
        return reply
