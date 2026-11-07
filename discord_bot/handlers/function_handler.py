from ..functions.base import BaseFunction
import asyncio, importlib, inspect, json, pkgutil, logging, time

class FunctionHandler:
    def __init__(self):
        # Dynamically load all functions from the functions package
        self.functions = self.load_functions()
        self.api_functions = self.get_api_functions()

    def load_functions(self):
        # Dynamically import all modules in the 'functions' package
        package_name = 'discord_bot.functions'
        package = importlib.import_module(package_name)

        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            importlib.import_module(f"{package_name}.{module_name}")

        # Logic to load all function classes
        loaded_functions = {cls().name: cls for cls in BaseFunction.__subclasses__() if cls != BaseFunction}

        return loaded_functions

    async def execute_function(self, function_name, args):
        started = time.monotonic()
        try:
            function_class = self.functions.get(function_name)
            if function_class:
                # Convert args string to dictionary
                if isinstance(args, str):
                    args = json.loads(args)
                instance = function_class()
                result = instance.execute(args)
                result = await asyncio.wait_for(result, timeout=30) if inspect.isawaitable(result) else result
                failed = False
                if isinstance(result, str):
                    try:
                        payload = json.loads(result)
                        failed = isinstance(payload, dict) and payload.get("ok") is False
                    except (ValueError, TypeError):
                        pass
                logging.log(logging.WARNING if failed else logging.INFO,
                            'Tool %s: name=%s duration_ms=%d',
                            'reported failure' if failed else 'completed',
                            function_name, int((time.monotonic() - started) * 1000))
                return result
            raise ValueError(f"Function {function_name} not found.")
        #TODO: Catch specific exceptions and return a more specific error message
        #TODO: handle timeouts errors
        except Exception as e:
            logging.warning('Tool failed: name=%s error_type=%s duration_ms=%d', function_name, type(e).__name__, int((time.monotonic() - started) * 1000))
            return "An error occurred while executing the function."

    def get_api_functions(self):
        api_functions = []
        
        for func_name, func_class in self.functions.items():
            instance = func_class()
            api_functions.append({
                'name': func_name,
                'description': instance.description,
                'parameters': instance.get_parameters()
            })
        
        logging.info('Registered %d tools: %s', len(api_functions), ', '.join(item['name'] for item in api_functions))

        return api_functions