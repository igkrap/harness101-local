import re

def validate_error_payloads(criteria):
    def get_route(path):
        parts = path.split('?') [0].split('/')
        return '/'.join(p if not re.match(r'^\d+$', p) else '{id}' for p in parts)

    peers = {}
    for c in criteria:
        try:
            chk = c['check']
            if chk.get('op') == 'api' and 200 <= chk.get('status', 0) < 300:
                key = (chk['method'], get_route(chk['path']))
                body = chk.get('body')
                if isinstance(body, dict) and body:
                    peers.setdefault(key, []).append(body)
        except (KeyError, TypeError):
            continue

    for c in criteria:
        try:
            chk = c['check']
            if chk.get('op') != 'api' or chk.get('status') != 404 or chk.get('method') not in ('PUT', 'PATCH'):
                continue
            
            method, route = chk['method'], get_route(chk['path'])
            target_peers = peers.get((method, route), [])
            if not target_peers:
                continue

            err_body = chk.get('body')
            if not isinstance(err_body, dict):
                ref_keys = sorted(target_peers[0].keys())
                raise ValueError(f"Criterion {c['id']}: 404 check must send otherwise valid request body, matching successful request fields: [{', '.join(ref_keys)}]; missing/partial body would test 400 request validation instead of missing-ID 404. Reference peer keys: {ref_keys}")

            valid_match = False
            for p_body in target_peers:
                if all(k in err_body for k in p_body.keys()):
                    valid_match = True
                    break
            
            if not valid_match:
                # Find the first peer's keys to satisfy the error message requirement
                # The requirement asks for expected sorted bodyfields
                ref_keys = sorted(target_peers[0].keys())
                raise ValueError(f"Criterion {c['id']}: 404 check must send otherwise valid request body, matching successful request fields: [{', '.join(ref_keys)}]; missing/partial body would test 400 request validation instead of missing-ID 404. Reference peer keys: {ref_keys}")
        except KeyError:
            continue
