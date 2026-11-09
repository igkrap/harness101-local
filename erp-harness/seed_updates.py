import os
import re
import json
import glob
import math
from pathlib import Path

SEED_TOOL = {
    "type": "function",
    "function": {
        "name": "update_seed_rows",
        "description": "Update existing seed/example rows in the database and sync test expectations.",
        "parameters": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "minimum": 1},
                            "old_values": {
                                "type": "object",
                                "additionalProperties": {"type": ["string", "number", "boolean", "null"]}
                            },
                            "values": {
                                "type": "object",
                                "additionalProperties": {"type": ["string", "number", "boolean", "null"]}
                            }
                        },
                        "required": ["id", "old_values", "values"]
                    }
                }
            },
            "required": ["table", "rows"]
        }
    }
}

def is_seed_request(task: str) -> bool:
    from seed_intent import is_seed_task
    return is_seed_task(task)

def _sql_val(v):
    if v is None: return "NULL"
    if isinstance(v, bool): return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)): return str(v)
    return "'" + str(v).replace("'", "''") + "'"

def _sql_pred(k, v):
    if v is None: return k + " IS NULL"
    if isinstance(v, bool): return k + " = " + ("TRUE" if v else "FALSE")
    if isinstance(v, (int, float)): return k + " = " + str(v)
    return k + " = '" + str(v).replace("'", "''") + "'"

def seed_edits(root: str, args: dict) -> list:
    table = args["table"]
    rows = args["rows"]
    base = Path(root).resolve()
    from seed_validation import validate_seed_args
    validate_seed_args(args)
    
    # Validation
    if not re.match(r"^[a-z][a-z0-9_]*$", table): raise ValueError("Invalid table name")
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)) or any(not isinstance(i, int) or i <= 0 for i in ids):
        raise ValueError("Invalid or duplicate IDs")
    
    replacements = {}
    ambiguous = set()
    sql_lines = []
    for r in rows:
        if "id" in r["values"] or "created_at" in r["values"]: raise ValueError("Cannot update id/created_at")
        if not r["old_values"] or not r["values"]: raise ValueError("Empty maps")
        
        set_clauses = []
        where_clauses = [f"id = {r['id']}"] + [_sql_pred(k, r['old_values'][k]) for k in sorted(r['old_values'])]
        for k in sorted(r["values"].keys()):
            val = r["values"][k]
            if not isinstance(val, (str, int, float, bool, type(None))): raise ValueError("Invalid type")
            if isinstance(val, str) and len(val) > 500: raise ValueError("String too long")
            set_clauses.append(f"{k} = {_sql_val(val)}")
            
            if k in r["old_values"]:
                old_v = r["old_values"][k]

                if isinstance(old_v, str) and isinstance(val, str) and old_v != val:
                    if old_v in replacements and replacements[old_v] != val:
                        ambiguous.add(old_v)
                    replacements[old_v] = val

        sql_lines.append(f"UPDATE {table} SET {', '.join(set_clauses)} WHERE {' AND '.join(where_clauses)};")

    # Migration logic
    mig_dir = base / "backend" / "src" / "main" / "resources" / "db" / "migration"
    if not mig_dir.exists(): raise ValueError("Migration dir not found")
    
    existing_tables = set()
    versions = []
    for f in mig_dir.glob("V*.sql"):
        if not f.is_symlink():
            versions.append(f.name)
            content = f.read_text()
            existing_tables.update(re.findall(r"CREATE TABLE\s+([a-z0-9_]+)", content, re.I))
    
    if table not in existing_tables: raise ValueError(f"Table {table} not found in migrations")
    
    v_nums = []
    for v in versions:
        m = re.match(r"V(\d+)(?:__.*)", v)
        if m: v_nums.append(int(m.group(1)))
    next_v = max(v_nums) + 1 if v_nums else 1
    new_sql_path = mig_dir / f"V{next_v}__update_seed_examples.sql"
    
    # Test updates
    test_dir = base / "backend" / "src" / "test"
    edits = []
    for test_file in test_dir.rglob("*.java"):
        if test_file.is_symlink(): continue
        content = test_file.read_text()
        new_content = content
        for old_s, new_s in replacements.items():
            # Target .value("old") pattern
            target = f'.value("{json.dumps(old_s, ensure_ascii=False)[1:-1]}")'
            replacement = f'.value("{json.dumps(new_s, ensure_ascii=False)[1:-1]}")'
            if target in new_content:
                if old_s in ambiguous:
                    raise ValueError(f"Ambiguous replacement for expected string: {old_s}")
                new_content = new_content.replace(target, replacement)
        
        if new_content != content:
            edits.append({"name": "edit_file", "args": {"path": str(test_file.relative_to(base)), "old_text": content, "new_text": new_content}})

    edits.append({"name": "write_file", "args": {"path": str(new_sql_path.relative_to(base)), "content": "\n".join(sql_lines)}})
    return edits
