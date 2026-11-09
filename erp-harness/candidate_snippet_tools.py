import json
from types import SimpleNamespace
from divide_plan import duplicate_hook
from tool_input_validation import validate_arguments

TOOL_NAME = 'apply_snippet_patch'

def tool_spec(catalog):
    """Returns the OpenAI function specification for applying snippet patches."""
    schema = {
        "type": "object",
        "properties": {
            "patches": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "enum": sorted(list(catalog.keys()))},
                        "old_text": {"type": "string", "maxLength": 3000},
                        "new_text": {"type": "string", "maxLength": 3000},
                    },
                    "required": ["node_id", "old_text", "new_text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["patches"],
        "additionalProperties": False,
    }
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Apply literal source snippets within ACTIVE node; unique exact old_text, empty old only empty AST slots, empty new deletion, all related edits atomic.",
            "parameters": schema,
        },
    }

def parse_tool_patches(response, catalog):
    """Parses tool calls from an assistant message and validates them."""
    tool_calls = response.get("tool_calls")
    if not tool_calls:
        return None

    spec = tool_spec(catalog)
    proxy = SimpleNamespace(tools=lambda: [spec])
    aggregated_patches = []

    for call in tool_calls:
        if not isinstance(call, dict) or "function" not in call:
            raise ValueError("Malformed tool call structure.")
        
        func = call["function"]
        if func.get("name") != TOOL_NAME:
            raise ValueError(f"Expected function name {TOOL_NAME}, got {func.get('name')}")

        args_raw = func.get("arguments")
        if isinstance(args_raw, str):
            args = json.loads(args_raw, object_pairs_hook=duplicate_hook)
        elif isinstance(args_raw, dict):
            args = args_raw
        else:
            raise ValueError("Function arguments must be a JSON string or dict.")

        validate_arguments(proxy, TOOL_NAME, args)
        
        patches = args.get("patches", [])
        if not isinstance(patches, list):
            raise ValueError("Argument 'patches' must be an array.")
        aggregated_patches.extend(patches)

    if len(aggregated_patches) < 1 or len(aggregated_patches) > 8:
        raise ValueError(f"Total patches must be between 1 and 8, got {len(aggregated_patches)}")

    return aggregated_patches
