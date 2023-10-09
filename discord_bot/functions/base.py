class BaseFunction:
    name = "base_function"
    description = "Base function, not to be used directly.  A well crafted description is critical and informs the LLM about the purpose of the function."
    parameters = {
                    "type": "object", 
                    "properties": {
                        "param1": {
                            "type": "string",
                            "description": "A well crafted description informs the LLM about the purpose of the parameter."
                            },
                            
                        "param2": {
                            "type": "number",
                            "description": "Some parameters can be optional, but should still have a well crafted description."
                            }
                        },
                    "required": ["param1"]
                    }


    async def execute(self, args):
        raise NotImplementedError
    
    @classmethod
    def get_parameters(cls):
        base_params = {
            "type": "object",
            "properties": {
                "quick_update": {
                    "type": "string",
                    "description": "A very brief message to send back to the user explaining your thought process and telling them what you're doing.  Don't include this when storing a memory."
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
