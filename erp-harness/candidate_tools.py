"""
Constants defining OpenAI tool definitions for AST manipulation.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "repair_ast_candidate",
            "description": (
                "Revise retained failed AST transaction. Change/add only faulty node fragments; "
                "harness retains every unchanged companion edit and reapplies entire proposal "
                "atomically using original snapshot. Original files have been restored. "
                "Do not regenerate wholefile. New nodeIDs must come from same original file snapshot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "node_id": {"type": "string"},
                                "code": {"type": "string"},
                            },
                            "required": ["node_id", "code"],
                            "additionalProperties": False,
                        },
                    },
                    "remove": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["changes", "remove"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discard_ast_candidate",
            "description": (
                "Discard failed proposal without source changes; resume normal tools "
                "with current original code"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]
