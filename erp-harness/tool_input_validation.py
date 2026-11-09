import json
import subprocess
import shutil
from pathlib import Path

def validate_arguments(runner, name, inputs):
    """Validates tool inputs against schemas retrieved from the runner."""
    schema = None
    for tool in runner.tools():
        if isinstance(tool, dict) and "function" in tool:
            if tool["function"].get("name") == name:
                schema = tool["function"].get("parameters")
                break
        elif isinstance(tool, dict) and tool.get("name") == name:
            schema = tool.get("parameters")
            break

    if schema is None:
        return None
    if not isinstance(schema, dict):
        return None

    node = shutil.which("node") or str(Path.home() / ".nvm/versions/node/v22.15.0/bin/node")
    validator_path = Path(__file__).with_name("tool_schema_validator.cjs")

    try:
        result = subprocess.run(
            [node, str(validator_path)],
            input=json.dumps({"schema": schema, "arguments": inputs}),
            capture_output=True,
            text=True,
            timeout=10
        )
    except Exception as e:
        raise ValueError(f"Validator infrastructure error: {str(e)}") from e

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("Validator failed to return valid JSON output.")

    if result.returncode == 0 and output.get("valid") is True:
        return None

    errors = output.get("errors", [])
    error_details = []
    for err in errors:
        detail = f"{err.get('dataPath', '')} {err.get('params', '')} {err.get('message', '')}"
        error_details.append(detail.strip())

    error_msg = (
        f"TOOL_INPUT_INVALID {name}: {', '.join(error_details)}. "
        f"Expected arguments schema: {json.dumps(schema, ensure_ascii=False)}"
    )
    # Cap error message at 3500 chars as per requirement
    raise ValueError(error_msg[:3500])
