from ..functions.base import BaseFunction, tool_error
from ..functions.discord_message_function import GetDiscordMessage
from ..functions.react_to_message import ReactToMessage
import asyncio, importlib, inspect, json, pkgutil, logging, time

TOOL_TIMEOUT = 30


CONTEXT_TOOLS = frozenset({
    "search_discord_history", "get_discord_conversation_context", ReactToMessage.name,
    GetDiscordMessage.name,
})


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

    async def execute_function(self, function_name, args, context=None):
        function_class = self.functions.get(function_name)
        if function_class is None:
            return tool_error("UNKNOWN_TOOL", "Choose an available tool.")
        try:
            if isinstance(args, str):
                args = json.loads(args)
        except json.JSONDecodeError:
            args = None
        if not isinstance(args, dict):
            return tool_error("INVALID_ARGUMENT", "Provide a JSON object matching the tool schema.", retryable=True)

        started = time.monotonic()
        try:
            instance = function_class()
            if function_name in CONTEXT_TOOLS:
                execute, execution_args = instance.execute_with_context, (args, context)
            else:
                execute, execution_args = instance.execute, (args,)
            async with asyncio.timeout(TOOL_TIMEOUT):
                if inspect.iscoroutinefunction(execute):
                    result = execute(*execution_args)
                else:
                    result = await asyncio.to_thread(execute, *execution_args)
                if inspect.isawaitable(result):
                    result = await result
        except asyncio.TimeoutError:
            result = tool_error("TIMEOUT", "Tool timed out. Try another source or retry if budget allows.", retryable=True)
        except Exception as exc:
            logging.warning("Tool exception: name=%s error_type=%s", function_name, type(exc).__name__)
            result = tool_error("PROVIDER_ERROR", "Tool execution failed. Try another source or use gathered information.")

        try:
            payload = json.loads(result)
        except (ValueError, TypeError):
            payload = None
        failed = isinstance(payload, dict) and payload.get("ok") is False
        if failed:
            error = payload.get("error")
            if not isinstance(error, dict):
                error = {"code": "TOOL_ERROR", "message": str(error or "Tool execution failed.")}
                payload["error"] = error
            error.setdefault("code", "TOOL_ERROR")
            error.setdefault("retryable", False)
            result = json.dumps(payload)
        logging.log(logging.WARNING if failed else logging.INFO,
                    "Tool %s: name=%s duration_ms=%d",
                    "reported failure" if failed else "completed",
                    function_name, int((time.monotonic() - started) * 1000))
        return result

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
