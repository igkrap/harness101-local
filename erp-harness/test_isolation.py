import json
import re
from typing import Any, Dict
from java_annotations import annotation_arguments

"""
Export raw OpenAI tool schema ISOLATION_TOOL
"""
ISOLATION_TOOL = {
    "type": "function",
    "function": {
        "name": "isolate_spring_test",
        "description": "Preferred for Spring integration test isolation: adds transactional rollback and BEFORE_TEST_METHOD SQL cleanup of known test-created rows only, preserving all imports, assertions and seed rows. Supply raw single scoped DELETE SQL, not Java literals.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "cleanup_sql": {"type": "string"}
            },
            "required": ["path", "cleanup_sql"]
        }
    }
}


def isolation_arguments(inputs: Dict[str, Any], current: str) -> Dict[str, Any]:
    """
    Validates input and returns exact native edit arguments for the transactional harness.
    """
    path = inputs.get("path")
    sql = inputs.get("cleanup_sql")

    if not isinstance(path, str) or not isinstance(sql, str):
        raise ValueError("path and cleanup_sql must be strings")

    if len(sql) > 1200:
        raise ValueError("cleanup_sql exceeds max length of 1200")

    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].strip()

    # Regex: single DELETE FROM [table] WHERE [nonempty predicate]
    # Case insensitive, no semicolon, no forbidden keywords, no trivial predicates
    pattern = r"(?i)^DELETE\s+FROM\s+\w+\s+WHERE\s+(?!(?:1\s*=\s*1|TRUE|true|FALSE|false)\b)(?!\s*(?:DROP|TRUNCATE|INSERT|UPDATE)\b).+$"
    
    if not re.fullmatch(pattern, sql):
        raise ValueError("SQL must be a single DELETE FROM statement with a non-trivial WHERE clause")

    if ";" in sql:
        raise ValueError("SQL must not contain semicolons")

    # Forbidden keywords check (redundant but safe)
    forbidden = ["DROP", "TRUNCATE", "INSERT", "UPDATE"]
    if any(kw in sql.upper() for kw in forbidden):
        raise ValueError(f"SQL contains forbidden keyword")

    # Validate file context
    if not path.endswith(".java"):
        raise ValueError("path must end with .java")

    if "@SpringBootTest" not in current:
        raise ValueError("current file must contain @SpringBootTest")

    # json.dumps handles Java string quoting/escaping correctly for the annotation value
    sql_json_escaped = json.dumps(sql, ensure_ascii=False)
    
    return annotation_arguments({
        'path': path,
        'annotations': [
            'org.springframework.transaction.annotation.Transactional',
            f'org.springframework.test.context.jdbc.Sql(statements = {sql_json_escaped})'
        ]
    }, current)
