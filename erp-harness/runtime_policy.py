import os
import re

def plan_prompt(task: str, feedback: str) -> str:
    """Instructs model to return a single atomic JSON implementation step."""
    return (
        f"Task: {task}\n"
        f"Feedback: {feedback}\n"
        "Return ONLY a JSON object: {\"steps\":[{\"title\":\"...\",\"kind\":\"change\"}]}. "
        "Provide exactly one atomic implementation change step matching the goal. "
        "No boilerplate. Baseline failures are feedback to fix."
    )

def frontend_contract(modes: list) -> str:
    """Returns Astryx contract if frontend or framework modes are present."""
    if not any(m in ("frontend", "framework") for m in modes):
        return ""
    return (
        "Astryx contract: preserve accessible labels; when an icon-only button is needed, use isIconOnly and retain its accessible label; "
        "do not nest interactive elements; for existing TS/TSX edits, prefer inspect_code action 'edit_ranges' then 'apply_ast_edits' (no arbitrary offsets, old_text, or whole-file regeneration); write_file allowed for NEW files; read component docs tool on demand ONLY when "
        "a component change is needed. Do not prefetch docs."
    )

def preserve_java_assertions(before: str, after: str, task: str) -> bool:
    from java_assertion_policy import preserved
    return preserved(before, after, task)

def generation_settings() -> dict:
    """Returns validated LLM settings from environment variables."""
    try:
        temp = float(os.environ.get("LOCAL_LLM_TEMPERATURE", 1.0))
        timeout = int(os.environ.get("LOCAL_LLM_TIMEOUT", 600))
    except ValueError:
        raise ValueError("Environment variables must be numeric.")

    if not (0.0 <= temp <= 2.0):
        raise ValueError("Temperature must be between 0 and 2.")
    if not (30 <= timeout <= 3600):
        raise ValueError("Timeout must be between 30 and 3600.")

    return {"temperature": temp, "timeout": timeout}
