from typing import Any, Dict, List, Union
from edit_tools import insert_arguments
from edit_limits import MAX_SOURCE_CHARS

def batch_arguments(inputs: Dict[str, Any], current: str) -> Dict[str, str]:
    """
    Apply ALL additions to a small source file in ONE verified transaction.
    Use for imports AND class annotations together; existing code preserved automatically.
    Source and result max MAX_SOURCE_CHARS chars.

    Args:
        inputs: Dictionary containing 'path' (str) and 'blocks' (list of dicts).
        current: The current content of the file.

    Returns:
        A dictionary containing the path, the original text, and the new text.

    Raises:
        ValueError: If constraints are violated or anchor text is not found exactly once.
    """
    path = inputs.get("path")
    blocks = inputs.get("blocks")

    if not isinstance(path, str):
        raise ValueError("path must be a string")
    if not isinstance(blocks, list) or not (1 <= len(blocks) <= 8):
        raise ValueError("blocks must be a list of 1 to 8 objects")
    if not isinstance(current, str) or not (0 < len(current) <= MAX_SOURCE_CHARS):
        raise ValueError(f"current content must be a non-empty string <= {MAX_SOURCE_CHARS} chars")

    candidate = current

    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("each block must be an object")
        
        # Validate block structure using the provided tool
        # insert_arguments is expected to validate anchor, text, and position
        args = insert_arguments({"path": path, **block})
        
        # The tool returns the transformation details. 
        # We must ensure the anchor/old_text exists exactly once to prevent ambiguity.
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        
        if candidate.count(old_text) != 1:
            raise ValueError(f"Anchor text '{old_text}' must appear exactly once in the source")

        # Apply the transformation to the candidate string
        candidate = candidate.replace(old_text, new_text, 1)

    if len(candidate) > MAX_SOURCE_CHARS:
        raise ValueError(f"Resulting text exceeds {MAX_SOURCE_CHARS} characters")

    return {
        "path": path,
        "old_text": current,
        "new_text": candidate
    }

BATCH_TOOL = {
    "name": "apply_insertions",
    "description": "Apply all additive edits to a small source file in ONE verified transaction; use for imports and class annotations together. Existing source automatically preserved. Max source/result " + str(MAX_SOURCE_CHARS) + " chars.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string"
            },
            "blocks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "anchor": {
                            "type": "string"
                        },
                        "text": {
                            "type": "string"
                        },
                        "position": {
                            "type": "string",
                            "enum": [
                                "before",
                                "after"
                            ]
                        }
                    },
                    "required": [
                        "anchor",
                        "text",
                        "position"
                    ]
                }
            }
        },
        "required": [
            "path",
            "blocks"
        ]
    }
}
