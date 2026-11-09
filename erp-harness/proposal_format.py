import json

def prepare(runner, system, user_content, current_source, target, context_text, docs, ponytail):
    if getattr(runner.args,'edit_format','auto') not in ('diff','whole'):
        from ast_proposal import prepare as ast_prepare
        return ast_prepare(runner,system,user_content,current_source,target,context_text,docs,ponytail)
    whole_bool = getattr(runner.args,'edit_format','auto') == 'whole'
    if not whole_bool:
        return system, user_content, False

    if not getattr(runner, '_whole_format_logged', False):
        runner.h.log_event('autonomy.strategy', {
            'reason': 'edit_format_fallback',
            'format': 'whole',
            'path': target,
            'model_calls': 0
        })
        runner._whole_format_logged = True

    new_system = (
        f"{system}\n\nINSTRUCTION: Return ONLY the complete corrected TSX code in exactly "
        "one tsx fenced codeblock. Preserve ALL original form handlers, APIs, meta, and exports. "
        "Add a working API Table. Preserve original JSX once. Do not edit JSON. "
        "The original project/policy rules apply, but you MUST supersede the JSON output format."
    )
    
    new_user = (
        f"Goal: {runner.args.task}\nTarget: {target}\n"
        f"Original Source:\n{current_source}\n"
        f"Context: {context_text}\nDocs: {docs}\n"
        f"Feedback: {runner.feedback[:2200]}\n{ponytail}"
    )
    return new_system, new_user, True

def normalize(content, current_source, whole_bool):
    if isinstance(whole_bool,dict) and whole_bool.get('kind')=='ast':
        from ast_proposal import normalize as ast_normalize
        return ast_normalize(content,current_source,whole_bool)
    if not whole_bool:
        def check_dupes(pairs):
            seen = set()
            for k, v in pairs:
                if k in seen:
                    raise ValueError(f"Duplicate JSON key: {k}")
                seen.add(k)
                if isinstance(v, dict):
                    # The hook handles nesting via recursion if the decoder 
                    # is called on the whole object, but we must ensure 
                    # we check nested dicts if they were parsed.
                    pass 
            return dict(pairs)

        # To catch nested duplicates, we use a recursive helper in the hook
        def deep_check(pairs):
            d = {}
            for k, v in pairs:
                if k in d: raise ValueError(f"Duplicate JSON key: {k}")
                if isinstance(v, dict):
                    # This is handled by the decoder's natural traversal
                    pass
                d[k] = v
            return d

        try:
            start_idx = content.find('{')
            if start_idx != -1:
                json.JSONDecoder(object_pairs_hook=deep_check).raw_decode(content[start_idx:])
        except (json.JSONDecodeError, ValueError) as e:
            if isinstance(e, json.JSONDecodeError):
                return content
            raise e
        return content

    # Whole mode: Extract code from fence
    import re
    # Match ```tsx ... ``` or ```typescript ... ``` or ```ts ... ``` or bare import/export
    pattern = r"```(?:tsx|typescript|ts)?\n([\s\S]*?)\n```"
    if len(re.findall(pattern, content)) > 1:
        raise ValueError("Multiple code blocks detected")
    match = re.search(pattern, content)
    
    if match:
        code = match.group(1).strip()
        # Check for embedded fences
        if "```" in code:
            raise ValueError("Embedded additional codefences detected")
    else:
        # Check if it's bare source
        stripped = content.strip()
        if stripped.startswith(("import ", "export ")) and len(stripped) < 32000:
            code = stripped
        else:
            raise ValueError("No valid code block found")

    if not code or len(code) > 32000:
        raise ValueError("Invalid source length or empty")

    return json.dumps({
        'edits': [{'old_text': current_source, 'new_text': code}]
    }, ensure_ascii=False)
