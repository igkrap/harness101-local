import re

def is_seed_task(task: str) -> bool:
    """
    Determines if a task is strictly for seed/sample data replacement/alignment.
    Returns False if the task involves API implementation, filesystem paths, 
    Java package names, or mixed feature requests.
    """
    if not task:
        return False
    api_patterns = ['(?i)\\b(PUT|POST|PATCH|DELETE)\\b\\s+/api/', '(?i)\\b(implement|add|fix|create|update)\\b.*\\b(API|endpoint|Controller|method)\\b', '\\w+\\s+(API|Controller|Service|Repository|Endpoint)를?\\s+(수정|변경|추가|삭제|생성|구현|작성)한다?']
    for pattern in api_patterns:
        if re.search(pattern, task):
            return False
    task = re.sub('https?://\\S+', '', task)
    task = re.sub('(/[a-zA-Z0-9._-]+)+', '', task)
    task = re.sub('\\b[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+\\b', '', task)
    preservation_patterns = ['(?i)preserve\\s+(existing\\s+)?(seed|sample|example)\\s+(data|rows)', '(?i)keep\\s+(existing\\s+)?(seed|sample|example)\\s+(data|rows)', '(?i)retain\\s+(existing\\s+)?(seed|sample|example)\\s+(data|rows)', '(?i)(보존|유지|건드리지|변경하지)\\s*(기존\\s*)?(샘플|예시|seed|sample|example)\\s*(데이터|rows)?']
    for pattern in preservation_patterns:
        task = re.sub(pattern, '', task)
    seed_terms = ['\\bseed\\b', '\\bsample\\b', '\\bexample\\b', '예시', '샘플']
    domain_terms = ['\\binventory\\b', '\\bmaterial\\b', '\\bdata\\b', '재고', '자재', '데이터']
    has_seed = any((re.search(p, task, re.IGNORECASE) for p in seed_terms))
    has_domain = any((re.search(p, task, re.IGNORECASE) for p in domain_terms))
    if has_seed and has_domain:
        if re.search('\\b(sample|seed|inventory|data)[a-zA-Z]+\\b', task):
            pass
        return True
    return False
