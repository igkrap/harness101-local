import re
import math

def validate_seed_args(args: dict) -> None:
    if not isinstance(args, dict):
        raise ValueError("args must be dict")
    pattern = re.compile(r"[a-z][a-z0-9_]*")
    if not isinstance(args.get("table"), str) or not pattern.fullmatch(args["table"]):
        raise ValueError("invalid table")
    rows = args.get("rows")
    if not isinstance(rows, list) or not (1 <= len(rows) <= 50):
        raise ValueError("rows must be list 1..50")
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("row must be dict")
        rid = row.get("id")
        if not isinstance(rid, int) or isinstance(rid, bool) or rid <= 0 or rid in ids:
            raise ValueError("invalid id")
        ids.add(rid)
        for key in ("values", "old_values"):
            data = row.get(key)
            if not isinstance(data, dict) or not data:
                raise ValueError(f"{key} must be nonempty dict")
            for k, v in data.items():
                if not isinstance(k, str) or not pattern.fullmatch(k):
                    raise ValueError("invalid key")
                if k in ("id", "created_at"):
                    raise ValueError("cannot update id or created_at")
                if v is not None:
                    if not isinstance(v, (bool, int, float, str)) or isinstance(v, bool) and not isinstance(v, bool):
                        pass # bool is int, handled by type check
                    if isinstance(v, bool):
                        continue
                    if isinstance(v, int):
                        continue
                    if isinstance(v, float):
                        if not math.isfinite(v):
                            raise ValueError("float not finite")
                    elif isinstance(v, str):
                        if len(v) > 500:
                            raise ValueError("string too long")
                    else:
                        raise ValueError("invalid type")
