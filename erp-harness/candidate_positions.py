def utf16_column_bytes(line: str, column: int) -> int:
    if not isinstance(line, str) or not isinstance(column, int) or column < 1:
        raise ValueError("Invalid input types or column index")
    le_bytes = line.encode('utf-16-le')
    byte_idx = (column - 1) * 2
    if byte_idx > len(le_bytes):
        raise ValueError("Column out of bounds")
    prefix = le_bytes[:byte_idx].decode('utf-16-le', errors='strict')
    return len(prefix.encode('utf-8'))
