import requests
from .base import BaseFunction
from bs4 import BeautifulSoup

class GetWebPageContents(BaseFunction):
    name = "get_webpage_contents"
    description = "Fetches the full content of a specific webpage based on its URL. Use this function to fetch detailed information from a specific webpage. Ideal for providing specific recommendations or in-depth answers. Use this especially when the query asks for specifics that a web search alone can't satisfy."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL of the webpage whose content you want to fetch. Make sure the URL points to a trustworthy and relevant source."}
        },
        "required": ["url"]
    }

    async def execute(self, args):
        url = args.get("url")
        if not url:
            return "You need to provide a URL."

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # Raise an HTTPError if one occurred

            soup = BeautifulSoup(response.content, 'lxml')
            
            # Remove some common unnecessary parts like scripts, styles, and footers
            for tag in soup.find_all(['script', 'style', 'footer']):
                tag.decompose()
            
            # Find the div with the most p tags inside it, assuming it's the main content
            #TODO: do this better, it skips a lot of content sometimes
            main_content_div = max(soup.find_all('div', recursive=True), 
                                key=lambda tag: len(tag.find_all('p', recursive=False)))

            text = main_content_div.get_text()

            # Break into lines and remove leading and trailing whitespace
            lines = (line.strip() for line in text.splitlines())
            
            # Break multi-headlines into a line each, and remove blank lines
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)

            # Limit to a certain amount of text to not flood the chat
            text = text[:4000] + "..." if len(text) > 4000 else text

            return text
        
        except requests.RequestException as e:
            return f"Error fetching the webpage: {e}"
