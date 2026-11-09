from types import SimpleNamespace
from tool_input_validation import validate_arguments

SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"const": "junit_added"},
        "suite": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^(?!.*\.\.)(?!.*\.$)(?!^\.)[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
        },
        "count": {"type": "integer", "minimum": 1, "maximum": 1000},
        "preserve_main": {"type": "boolean"}
    },
    "required": ["op", "suite", "count"],
    "additionalProperties": False
}

DSL_GUIDE = (
    "junit_added {op:'junit_added',suite:top-levelJavaFQCN,count:minimumADDEDexecutedtestsrelativebaseline,preserve_main?:bool}. "
    "Explains forJUnit test-addition requests use this notmanual; runsMaven/readsfreshSurefire pluschangedtestsource, "
    "preserve_maintruefortest-only; APIsequences mustbeseparateopapi criteria notscenario APIactions."
)

def validate_spec(check: dict) -> None:
    """
    Validates the provided check dictionary against the SCHEMA using the 
    installed AJV6-based validation wrapper.
    """
    validate_arguments(
        SimpleNamespace(tools=lambda: [{"name": "junit_added", "parameters": SCHEMA}]),
        "junit_added",
        check
    )
    return None
