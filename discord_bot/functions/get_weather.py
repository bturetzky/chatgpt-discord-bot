import os, requests, json, asyncio
from .base import BaseFunction

class WeatherLookup(BaseFunction):
    name = "weather_lookup"
    description = "Fetches weather data for a given location and time frame. Returns a JSON object with current, hourly, and daily forecasts."
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "The location for which to fetch the weather.  City name of the location"
            },
            "state": {
                "type": "string",
                "description": "Required if the country is the US. The location for which to fetch the weather.  State code (only for the US) of the location."
            },
            "country_code": {
                "type": "string",
                "description": "The location for which to fetch the weather.  Country code of the location. Please use ISO 3166 country codes."
            }
        },
        "required": ["city", "country_code"]
    }

    def __init__(self):
        self.api_key = os.environ.get('OPENWEATHER_API_KEY')

    async def execute(self, args):
        location = args.get('city')
        if args.get('state'):
            location += f",{args.get('state')}"
        location += f",{args.get('country_code')}"
        exclude = 'minutely'

        # Get latitude and longitude for the location using OpenWeather's geocoding API
        geocode_url = f"http://api.openweathermap.org/geo/1.0/direct?q={location}&limit=1&appid={self.api_key}"
        #print(geocode_url)
        try:
            geocode_response = await asyncio.to_thread(requests.get, geocode_url, timeout=10)
            geocode_response.raise_for_status()
            geocode_data = geocode_response.json()
            if not geocode_data:
                return f"No weather location found for {location}."
            lat, lon = geocode_data[0]['lat'], geocode_data[0]['lon']
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            return f"Unable to look up weather location: {type(exc).__name__}"

        # Make the API request for weather data
        url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&exclude={exclude}&appid={self.api_key}&units=imperial"
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
        except requests.RequestException as exc:
            return f"Unable to fetch weather: {type(exc).__name__}"
        #print(response.text)

        if response.status_code == 200:
            return self.trim_data(response.text)
        else:
            return f"Error fetching the weather: {response.content.decode('utf-8')}"
        
    def trim_data(self, data):
        data_dict = json.loads(data)
        
        # Trim hourly data to the first 24 hours
        if 'hourly' in data_dict:
            data_dict['hourly'] = data_dict['hourly'][:24]
        
        # Trim daily data to the next 3 days
        #if 'daily' in data_dict:
        #    data_dict['daily'] = data_dict['daily'][:3]
        
        return json.dumps(data_dict)