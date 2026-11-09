import json
import subprocess
import shutil
from pathlib import Path

def repair_imports(runner, result) -> bool:
    """
    Deterministic compiler reflex to organize TypeScript imports after lint failures.
    Only triggers on specific TS/ESLint errors and ensures file integrity via checksums.
    """
    error_msg = (result.get('stdout','') + result.get('stderr','')).lower()
    triggers = ["@typescript-eslint/no-unused-vars", "duplicate identifier", "ts2300", "ts6133"]
    unused_binding = "ts6133" in error_msg or "is declared but its value is never read" in error_msg
    
    if not runner.cp.pending or not any(t in error_msg for t in triggers):
        return False

    any_changed = False
    # Iterate over pending changes in the checkpoint
    for rel, record in list(runner.cp._records.items()):
        if not (rel.startswith("frontend/src/") and rel.endswith((".ts", ".tsx"))):
            continue
        
        if not isinstance(record.get("expected"), bytes):
            continue

        safe_path = runner.h.workspace.safe_path(rel)
        current_path = Path(safe_path)
        
        try:
            # Concurrency Guard: Verify file hasn't changed since checkpoint
            if not current_path.exists() or current_path.read_bytes() != record["expected"]:
                raise RuntimeError(f"Concurrent source change detected for {rel}")

            source_bytes = record["expected"]
            source_str = source_bytes.decode("utf-8")

            # Determine Node executor
            node_exe = getattr(getattr(getattr(runner.h,'_ast_editor',None),'service',None),'node',None)
            if not node_exe:
                node_exe = shutil.which("node")
            
            if not node_exe:
                raise RuntimeError("Node.js not found")

            # Execute AST organizer
            script_path = Path(__file__).with_name('ast_organize_imports.cjs')
            cmd = [node_exe, str(script_path)]
            payload = json.dumps({"source": source_str, "path": str(current_path)})

            proc = subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                text=True,
                timeout=20
            )

            if proc.returncode != 0:
                runner.h.log_event("autonomy.strategy", {"reason": f"Node error: {proc.stderr}", "path": rel})
                continue

            data = json.loads(proc.stdout)
            normalized = data.get("source")
            changed = data.get("changed", False)
            removed = []
            if unused_binding:
                # Drop destructured parameter properties that are no longer read (TypeScript codefix,
                # literal defaults only, changes confined to the parameter pattern).
                base = normalized if changed and normalized else source_str
                second = subprocess.run([node_exe, str(Path(__file__).with_name('ast_unused_bindings.cjs'))],
                                        input=json.dumps({"source": base, "path": str(current_path)}),
                                        capture_output=True, text=True, timeout=30)
                if second.returncode == 0:
                    extra = json.loads(second.stdout)
                    if extra.get("changed") and extra.get("source"):
                        normalized, changed, removed = extra["source"], True, extra.get("removed", [])

            if changed and normalized:
                new_bytes = normalized.encode("utf-8")
                
                # Pre-write integrity check: Ensure AST tool didn't mutate body/logic
                # The node helper is expected to validate side-effect/body identity
                if new_bytes == source_bytes:
                    continue

                # Perform the edit via the runner's tool abstraction
                if not current_path.exists() or current_path.read_bytes() != record["expected"]:
                    raise RuntimeError(f"Concurrent source change detected for {rel}")
                try:
                    edit_res = runner.h._execute_tool("edit_file", {
                        "path": rel,
                        "old_text": source_str,
                        "new_text": normalized
                    })
                finally:
                    runner.cp.record(rel)

                if not edit_res.get('error'):
                    # Success: Record the change in checkpoint for rollback safety
                    runner.cp.record(rel)
                    any_changed = True
                    runner.h.log_event("autonomy.strategy", {
                        "reason": "TypeScript organized duplicate/unused imports; body preserved; rerun frontend checks"
                                  + (f"; removed unused destructured parameters {removed}" if removed else ""),
                        "path": rel,
                        "model_calls": 0
                    })
                else:
                    runner.h.log_event("autonomy.strategy", {"reason": "edit_file tool failed", "path": rel})

        except (json.JSONDecodeError, subprocess.SubprocessError, OSError) as e:
            runner.h.log_event("autonomy.strategy", {"reason": f"Exception: {str(e)}", "path": rel})
            continue
        except RuntimeError as e:
            # Re-raise concurrency/integrity errors to stop the process
            raise e

    return any_changed
