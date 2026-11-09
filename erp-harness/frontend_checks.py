def run_frontend(checker):
    root = checker.workspace.root
    frontend_dir = f"{root}/frontend"
    
    from lint_frontend import run_lint
    lint_res = run_lint(checker)
    # Both fast checks describe the same candidate. A lint failure must not hide
    # missing exports or invalid component props until a later model round.
    type_res = checker._exec(["npx", "tsc", "--noEmit"], cwd=frontend_dir)
    results = [lint_res, type_res]
    if all(result['success'] for result in results):
        results.append(checker._exec(["npx", "vite", "build"], cwd=frontend_dir))
    failure = next((result for result in results if not result['success']), None)
    return {
        "success": failure is None,
        "exit_code": (failure.get('exit_code') or 1) if failure else 0,
        "stdout": "\n".join(r.get("stdout", "") for r in results),
        "stderr": "\n".join(r.get("stderr", "") for r in results),
        "lint": lint_res.get("lint", {})
    }
