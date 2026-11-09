import re

def unused_binding_targets(path, feedback, catalog):
    """
    Detects unused variable bindings from ESLint diagnostics matching specific 
    patterns and cross-references them with a provided AST catalog.
    """
    # Pattern: optional [frontend] prefix with whitespace, file path, line, col, error type, 
    # identifier, and the specific phrase 'is assigned a value but never used'.
    # The pattern now allows trailing text after the first sentence to match real compiler output.
    pattern = re.compile(
        r"^(?:\[frontend\]\s*)?(?P<file>.*?):(?P<line>\d+):(?P<col>\d+)\s+error\s+"
        r"@typescript-eslint/no-unused-vars\s+'(?P<var>[A-Za-z0-9_$]+)'\s+is "
        r"assigned a value but never used\..*$"
    )
    
    target_path = path
    found_ids = []
    hints = []
    seen_vars = set()
    seen_nodes = set()
    
    # Identifier regex for tokenizing destructuring annotations
    id_regex = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

    for line in feedback.splitlines():
        match = pattern.match(line)
        if not match:
            continue
            
        diag_file = match.group("file")
        if not (diag_file == target_path or diag_file.endswith("/" + target_path)):
            continue
            
        unused_name = match.group("var")
        
        # Find eligible catalog nodes matching the unused name
        matches = []
        for node in catalog:
            if node.get("kind") != "VariableStatement":
                continue
            
            label = node.get("label", "")
            if "[bindings:" in label:
                # Extract content between [bindings: and ]
                try:
                    content = label.split("[bindings:")[1].split("]")[0]
                    # Tokenize identifiers from the annotation string
                    tokens = id_regex.findall(content)
                    if unused_name in tokens:
                        matches.append(node["id"])
                except IndexError:
                    continue

        # If exactly one node matches, it's unambiguous
        if len(matches) == 1:
            node_id = matches[0]
            # If this specific node/var combo hasn't been recorded
            if unused_name not in seen_vars and node_id not in seen_nodes:
                found_ids.append(node_id)
                seen_vars.add(unused_name)
                seen_nodes.add(node_id)
                hints.append(
                    f"'{unused_name}' (ID: {node_id}) is unused; this declaration "
                    "lives outside retained edits: reuse/wire the existing "
                    "handler or revise that exact declaration."
                )
        # If len(matches) > 1, it is ambiguous; per requirement, we skip.

    return found_ids, " ".join(hints)
