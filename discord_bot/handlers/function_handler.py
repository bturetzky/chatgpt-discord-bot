from ..functions.base import BaseFunction
import importlib, json, pkgutil

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

    def execute_function(self, function_name, args):
        try:
            function_class = self.functions.get(function_name)
            if function_class:
                # Convert args string to dictionary
                if isinstance(args, str):
                    args = json.loads(args)
                instance = function_class()
                return instance.execute(args)
            raise ValueError(f"Function {function_name} not found.")
        #TODO: Catch specific exceptions and return a more specific error message
        #TODO: handle timeouts errors
        except Exception as e:
            print(f"Error occurred while executing function {function_name}: {e}")
            return "An error occurred while executing the function."

    def get_api_functions(self):
        api_functions = []
        
        for func_name, func_class in self.functions.items():
            instance = func_class()
            api_functions.append({
                'name': func_name,
                'description': instance.description,
                'parameters': instance.parameters
            })
        
        return api_functions