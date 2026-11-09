from seed_updates import seed_edits

def apply_seed(runner, inputs, before):
    operations = seed_edits(runner.h.workspace.root, inputs)
    for op in operations:
        name, args = op["name"], op["args"]
        if name == "edit_file":
            res = runner.apply('read_file', {'path': args['path']}, before)
            if 'error' in res: return res
            res = runner.apply(name, args, before)
            if 'error' in res: return res
        else:
            res = runner.apply(name, args, before)
            if 'error' in res: return res
    return {'status': 'success', 'paths': [op['args']['path'] for op in operations]}
