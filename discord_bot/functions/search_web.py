from .base import BaseFunction
from duckduckgo_search import AsyncDDGS

DDGS_DEFAULT_MAX_RESULTS = 4

class SearchWeb(BaseFunction):
    name = "search_web"
    description = ("Performs a web search using DuckDuckGo to retrieve a list of relevant webpages. Use this function as a starting point to find multiple sources or viewpoints for current events or topics outside your memory cut-off date. If the query asks for specific recommendations or detailed information, you can follow up by using 'get_webpage_contents' to dive into the links."
)
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
                results = [r async for r in ddgs.text(query, max_results=max_results)]
                #print(f"Raw results: {results}")
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
