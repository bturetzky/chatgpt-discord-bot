class BaseFunction:
    name = "base_function"
    description = "Base function, not to be used directly."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):
        raise NotImplementedError