import re
from candidate_field_pattern import FIELD_PATTERN

def normalize_field_fences(text: str) -> str:
    old_labels = r"OLD|OLD_TEXT|EXACT_OLD_SUBSTRING|BEFORE"
    new_labels = r"NEW|NEW_TEXT|REPLACEMENT_SUBSTRING|AFTER"
    pattern = re.compile(FIELD_PATTERN, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    matched_spans = []
    def replacer(match: re.Match) -> str:
        start, end = match.span()
        matched_spans.append((start, end))
        if match.group("canonical"):
            return match.group("canonical")
        label = match.group("label").upper()
        target = "```old" if any(x in label for x in ["OLD", "BEFORE"]) else "```new"
        return f"{target}{match.group('opening')}{match.group('body_content')}{match.group('closing')}"
    result = pattern.sub(replacer, text)
    validation_pattern = re.compile(rf"^(?:{old_labels}|{new_labels}|```(?:old|new))", re.MULTILINE | re.IGNORECASE)
    for m in validation_pattern.finditer(text):
        if not any(s <= m.start() < e for s, e in matched_spans):
            raise ValueError("Malformed or truncated field detected.")
    return result
