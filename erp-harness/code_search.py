import subprocess
import os
import json
import shutil
from pathlib import Path
from typing import Dict, Any, Union

SEARCH_TOOL = {
    "name": "search_code",
    "description": "Search codebase using exact or hybrid modes. Use 'exact' for identifiers/API/text, 'hybrid' for describing behavior. Use before guessing paths; read returned source paths with read_file before editing.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search term or natural language description."
            },
            "mode": {
                "type": "string",
                "enum": ["exact", "hybrid"],
                "default": "exact",
                "description": "Search mode: 'exact' for literal matches, 'hybrid' for semantic search."
            },
            "scope": {
                "type": "string",
                "enum": ["all", "frontend", "backend", "components"],
                "default": "all",
                "description": "The part of the codebase to search."
            }
        },
        "required": ["query"]
    }
}

def search_code(root: Path, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Searches the codebase using the 'zg' executable.
    """
    # 1. Validate Query
    query = args.get("query")
    if not isinstance(query, str):
        return {"success": False, "error": "Query must be a string"}
    
    query = query.strip()
    if not query:
        return {"success": False, "error": "Query cannot be empty"}
    if len(query) > 300:
        return {"success": False, "error": "Query exceeds 300 characters"}

    # 2. Validate Mode and Scope
    mode = args.get("mode", "exact")
    if mode not in ["exact", "hybrid"]:
        return {"success": False, "error": "Invalid mode. Must be 'exact' or 'hybrid'"}

    scope = args.get("scope", "all")
    if scope not in ["all", "frontend", "backend", "components"]:
        return {"success": False, "error": "Invalid scope. Must be all, frontend, backend, or components"}

    # 3. Setup Environment and Paths
    zg_path = Path.home() / ".local/share/mlx-server/search/node_modules/.bin/zg"
    if not zg_path.exists():
        return {"success": False, "error": f"Executable not found at {zg_path}"}

    model_cache = Path.home() / ".local/share/mlx-server/search/models"
    
    # Prepare PATH: prepend NVM node path
    nvm_node_bin = Path.home() / ".nvm/versions/node/v22.15.0/bin"
    env = os.environ.copy()
    current_path = env.get("PATH", "")
    if nvm_node_bin.exists():
        env["PATH"] = f"{nvm_node_bin}{os.pathsep}{current_path}"
    else:
        env["PATH"] = current_path

    # 4. Resolve Scope Directories (Non-symlink, existing)
    root_res = root.resolve()
    zvec_path = root_res / ".zvec-grep"
    if zvec_path.is_symlink():
        return {"success": False, "error": ".zvec-grep is a symlink"}
    
    def validate_tree(p: Path):
        if not p.exists() or not p.is_dir(): return False
        if p.is_symlink(): return False
        for part in p.parents:
            if part.is_symlink(): return False
        if not p.resolve().is_relative_to(root_res): return False
        return True

    def check_no_symlinks(p: Path):
        if not p.exists(): return True
        for item in p.rglob("*"):
            if item.is_symlink(): return False
        return True

    valid_roots = []
    for s in [("frontend", "frontend/src"), ("backend", "backend/src")]:
        p = root_res / s[1]
        if not p.exists(): continue
        for parent in [p, root_res / "frontend", root_res / "backend"]:
            if parent.exists() and parent.is_symlink(): return {"success": False, "error": f"Symlink in {parent.name}"}
        if not validate_tree(p) or not check_no_symlinks(p):
            return {"success": False, "error": f"Symlink detected in {s[1]}"}
        if scope == "all" or scope == s[0] or (scope == 'components' and s[0] == 'frontend'):
            valid_roots.append(s[1])

    for p_name, p_rel in [("frontend", "frontend/package.json"), ("backend", "backend/pom.xml")]:
        p = root_res / p_rel
        if p.exists() and (p.is_symlink() or any(a.is_symlink() for a in p.parents if a.is_relative_to(root_res))):
            return {"success": False, "error": f"{p_rel} is a symlink or has symlink parent"}

    if not valid_roots:
        return {"success": False, "error": "No allowed source roots found"}
    target_dirs = valid_roots

    # 5. Execution Logic
    try:
        if mode == "exact":
            # zg query --rg -n -F -m 5 -e QUERY [dirs]
            cmd = [
                str(zg_path), "query", "--rg", "-n", "-F", "-m", "5", "-e", query
            ] + target_dirs
            if scope == 'components':
                cmd.extend(['-g', '*.component.json'])
            
            result = subprocess.run(
                cmd, cwd=str(root), capture_output=True, text=True, timeout=30, env=env
            )
            
            # rc1 means successful no matches in zg context
            if result.returncode == 1:
                return {"mode": "exact", "content": "", "success": True, "truncated": False}
            if result.returncode != 0:
                return {"success": False, "error": f"Exact search failed: {result.stderr.strip()}"}
            
            content = result.stdout
            truncated = len(content) > 6000
            if truncated:
                content = content[:6000]
            
            return {"mode": "exact", "content": content, "success": True, "truncated": truncated}

        else:  # mode == "hybrid"
            # Check manifest constraints
            manifest = root / ".zvec-grep" / "manifest.json"
            if manifest.exists():
                try:
                    with open(manifest, "r") as f:
                        m_data = json.load(f)
                    if m_data.get("embedding", {}).get("provider") != "local" or \
                       m_data.get("embedding", {}).get("model") != "potion-multilingual-128m":
                        return {"success": False, "error": "Invalid manifest model/provider"}
                except Exception as e:
                    return {"success": False, "error": f"Invalid manifest JSON: {str(e)}"}

            # Indexing step
            # zg index --mode direct --embedding local/potion-multilingual-128m --model-cache CACHE --device cpu --embedding-concurrency 1 -g frontend/src/** -g backend/src/** -g frontend/package.json -g backend/pom.xml --max-filesize 200K
            index_cmd = [
                str(zg_path), "index", "--mode", "direct", 
                "--embedding", "local/potion-multilingual-128m",
                "--model-cache", str(model_cache),
                "--device", "cpu",
                "--embedding-concurrency", "1",
                "-g", "frontend/src/**",
                "-g", "backend/src/**",
                "-g", "frontend/package.json",
                "-g", "backend/pom.xml",
                "--max-filesize", "200K"
            ]
            
            idx_res = subprocess.run(index_cmd, cwd=str(root), capture_output=True, text=True, timeout=180, env=env)
            if idx_res.returncode != 0:
                err = idx_res.stderr[:2000] if idx_res.stderr else idx_res.stdout[:2000]
                return {"success": False, "error": f"Indexing failed (rc={idx_res.returncode}): {err}. Run index manually."}

            # Query step
            # zg query --mode direct --model-cache CACHE --device cpu --preview short --limit 5 --refresh off --hybrid QUERY
            query_cmd = [
                str(zg_path), "query", "--mode", "direct",
                "--model-cache", str(model_cache),
                "--device", "cpu",
                "--preview", "short",
                "--limit", "5",
                "--refresh", "off",
                "--hybrid", query
            ]
            
            # Add scope glob if applicable
            if scope == "frontend":
                query_cmd.extend(["-g", "frontend/src/**"])
            elif scope == "backend":
                query_cmd.extend(["-g", "backend/src/**"])
            elif scope == 'components':
                query_cmd.extend(['-g', 'frontend/src/**/*.component.json'])

            result = subprocess.run(
                query_cmd, cwd=str(root), capture_output=True, text=True, timeout=60, env=env
            )

            if result.returncode != 0:
                return {
                    "success": False, 
                    "error": f"Hybrid search failed: {result.stderr.strip()}. Try using 'exact' mode."
                }

            content = result.stdout
            truncated = len(content) > 6000
            if truncated:
                content = content[:6000]

            return {"mode": "hybrid", "content": content, "success": True, "truncated": truncated}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Search operation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}
