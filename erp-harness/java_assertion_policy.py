import re

def preserved(before: str, after: str, task: str) -> bool:

    def get_test_lines(content: str) -> list[str]:
        return [line for line in content.splitlines() if '@Test' in line]

    def get_assertion_lines(content: str) -> list[str]:
        return [line.strip() for line in content.splitlines() if '.andExpect(' in line]

    def clean(s):
        s = s.lower()
        s = re.sub('https?://\\S+', '', s)
        s = re.sub('(/[a-zA-Z0-9._-]+)+', '', s)
        s = re.sub('\\b[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+\\b', '', s)
        return s

    def norm(s):
        return re.sub('(\\.value\\s*\\(\\s*")(?:\\\\"|[^"])*?("\\s*\\))', '\\1[VALUE]\\2', s)

    def is_allowed(t):
        from seed_updates import is_seed_request
        if is_seed_request(t):
            return True
        t = clean(t)
        allow_seed = any((w in t for w in ['seed', 'sample', 'example', '예시', '샘플']))
        allow_change = any((w in t for w in ['change', 'rename', 'replace', '변경', '교체', '수정']))
        if allow_seed and allow_change:
            return True
        if any((w in t for w in ['예시로', '샘플로'])):
            return True
        return False
    if len(get_test_lines(after)) < len(get_test_lines(before)):
        return False
    base_assertions = get_assertion_lines(before)
    after_assertions = get_assertion_lines(after)
    if (allow_seed := is_allowed(task)):
        (base_assertions, after_assertions) = ([norm(l) for l in base_assertions], [norm(l) for l in after_assertions])
    it = iter(after_assertions)
    if not all((b in it for b in base_assertions)):
        return False
    return True
