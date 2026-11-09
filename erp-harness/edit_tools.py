from typing import Any, Dict

INSERT_TOOL = {
    "name": "insert_text",
    "description": "Insert additive source lines around a unique existing anchor, preserving the anchor. Prefer after a rejected rewrite.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "anchor": {"type": "string"},
            "text": {"type": "string"},
            "position": {"type": "string", "enum": ["before", "after"]}
        },
        "required": ["path", "anchor", "text", "position"]
    }
}


def insert_arguments(inputs: Dict[str, Any]) -> Dict[str, str]:
    """
    Validates inputs and returns the transformation mapping.
    Does not perform I/O.
    """
    required = ["path", "anchor", "text", "position"]
    for key in required:
        if key not in inputs:
            raise ValueError(f"Missing required argument: {key}")
        if not isinstance(inputs[key], str):
            raise ValueError(f"Argument {key} must be a string")

    path = inputs["path"]
    anchor = inputs["anchor"]
    text = inputs["text"]
    position = inputs["position"]

    if not anchor or len(anchor) > 800:
        raise ValueError("anchor must be non-empty and <= 800 chars")
    if not text or len(text) > 4000:
        raise ValueError("text must be non-empty and <= 4000 chars")
    if position not in ("before", "after"):
        raise ValueError("position must be 'before' or 'after'")

    if position == "before":
        new_text = text + anchor
    else:
        new_text = anchor + text

    return {
        "path": path,
        "old_text": anchor,
        "new_text": new_text
    }
