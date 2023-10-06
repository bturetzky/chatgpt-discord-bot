from .base import BaseFunction
from duckduckgo_search import AsyncDDGS

DDGS_MAX_RESULTS = 3

class SearchWeb(BaseFunction):
    name = "search_web"
    description = ("Executes a web search on DuckDuckGo to retrieve general information, "
                   "verify facts, or gather current data on a particular topic. Ideal for "
                   "questions that demand real-time answers or a broad search.")
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    async def execute(self, args):
        query = args.get("query")
        if not query:
            return "No search query provided."

        #TODO: switch to using a logger instead of this nonsense
        print(f"Searching the web for: {query}")
        try:
            async with AsyncDDGS() as ddgs:
                results = [r async for r in ddgs.text(query, max_results=DDGS_MAX_RESULTS)]
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
