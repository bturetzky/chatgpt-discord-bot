class BaseFunction:
    name = "base_function"
    description = "Base function, not to be used directly."
    parameters = {"type": "object", "properties": {}}


    async def execute(self, args):
        raise NotImplementedError
    
    @classmethod
    def get_parameters(cls):
        base_params = {
            "type": "object",
            "properties": {
                "quick_update": {
                    "type": "string",
                    "description": "A very brief message to send back to the user explaining your thought process and telling them what you're doing."
                }
            },
            "required": []
        }

        # Merge the 'properties' dictionaries
        merged_properties = {**base_params['properties'], **cls.parameters.get('properties', {})}

        # Create the final parameters dictionary
        final_params = {
            "type": "object",
            "properties": merged_properties,
            "required": base_params.get('required', []) + cls.parameters.get('required', [])
        }

        return final_params
