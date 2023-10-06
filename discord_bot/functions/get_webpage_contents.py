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

    @staticmethod
    def score_tag(tag):
        score = 0
        score += len(tag.find_all('p', recursive=False))
        score += len(tag.find_all(['ul', 'ol'], recursive=False)) * 2  # Give more weight to lists
        score += len(tag.find_all('li', recursive=False))
        return score


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
            
            # Find the tag with the highest score
            main_content_tag = max(soup.find_all(['div', 'article'], recursive=True), key=self.score_tag)

            # Extract and clean up the text
            text = main_content_tag.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)

            # Limit text length
            text = text[:4000] + "..." if len(text) > 4000 else text
            return text
        
        except requests.RequestException as e:
            return f"Error fetching the webpage: {e}"
