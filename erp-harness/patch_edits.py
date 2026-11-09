from typing import Any, Dict, List

def patch_arguments(inputs: Dict[str, Any], current: str) -> Dict[str, str]:
    """
    Applies a series of atomic text replacements to a string.
    Validates constraints on input sizes and ensures exact single-match replacements.
    """
    if not (0 < len(current) <= 32000):
        raise ValueError("current must be a non-empty string <= 32000 chars")

    path = inputs.get("path")
    if not isinstance(path, str):
        raise ValueError("inputs.path must be a string")

    edits = inputs.get("edits")
    if not isinstance(edits, list) or not (1 <= len(edits) <= 8) or not edits:
        raise ValueError("edits must be a list of 1 to 8 dictionaries")

    candidate = current
    for edit in edits:
        old_text = edit.get("old_text")
        new_text = edit.get("new_text")

        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise ValueError("old_text and new_text must be strings")
        if not old_text or old_text == new_text:
            raise ValueError("old_text must be non-empty and not equal to new_text")
        if len(old_text) > 32000 or len(new_text) > 32000:
            raise ValueError("edit text length must be <= 32000")

        if candidate.count(old_text) != 1:
            raise ValueError(f"Expected exactly one occurrence of '{old_text}'")

        candidate = candidate.replace(old_text, new_text, 1)

    if len(candidate) > 32000:
        raise ValueError("resulting candidate exceeds 32000 chars")

    return {
        "path": path,
        "old_text": current,
        "new_text": candidate
    }

PATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "apply_edits",
        "description": "Preferred for changing an existing file: replace several SMALL exact snippets in ONE verified transaction, preserving every other import, hook, handler and line. Use for component imports plus JSX changes together. Do not rewrite the whole file; each old/new snippet <=32000chars, source/result<=32000chars.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {
                                "type": "string"
                            },
                            "new_text": {
                                "type": "string"
                            }
                        },
                        "required": [
                            "old_text",
                            "new_text"
                        ]
                    },
                    "minItems": 1,
                    "maxItems": 8
                }
            },
            "required": [
                "path",
                "edits"
            ]
        }
    }
}
