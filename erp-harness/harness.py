import os
import sys
import json
import argparse
import subprocess
import urllib.request
import urllib.error
import time
from datetime import datetime
from pathlib import Path

# Constants
DEFAULT_LLM_URL = "http://127.0.0.1:8099/v1"
DEFAULT_MODEL = "mlx-community/Qwen3.8-27B-4bit"
MAX_BUDGET = int(os.environ.get('LOCAL_LLM_CONTEXT', '32768'))

class HarnessError(Exception):
    pass

class LocalLLMClient:
    def __init__(self, url, model):
        self.url = url.rstrip('/')
        self.model = model
        self.validate_url()

    def validate_url(self):
        # Reject non-loopback
        parsed = urllib.parse.urlparse(self.url)
        if parsed.hostname not in ('127.0.0.1', 'localhost'):
            raise HarnessError(f"Security violation: Non-loopback URL rejected: {self.url}")

    def chat(self, messages, tools=None):
        import os
        # Config from Env
        thinking_enabled = os.getenv("LOCAL_LLM_THINKING", "").lower() in ("true", "yes", "1")

        # Strict integer validation for max_tokens
        raw_max = os.getenv("LOCAL_LLM_MAX_TOKENS", "4096")
        try:
            max_tokens = int(raw_max)
            if not (1 <= max_tokens <= 12288):
                raise HarnessError(f"Invalid output token limit: {raw_max}")
        except ValueError:
            raise HarnessError(f"Invalid output token limit: {raw_max}")

        # Budget guard: 3 chars per token for serialized messages + tools + max_tokens reserved
        # We strip reasoning fields from messages to avoid double-counting/re-sending traces
        clean_messages = []
        for m in messages:
            cm = {k: v for k, v in m.items() if k not in ("reasoning", "reasoning_content")}
            if not cm.get("role"):
                cm["role"] = "assistant"  # helper-made replies without a role break the chat template
            clean_messages.append(cm)

        from context_budget import measure
        budget = measure(clean_messages, tools, reserved=max_tokens, capacity=MAX_BUDGET)
        estimated_tokens = budget['estimated_input_tokens'] + budget['reserved_output_tokens']

        if estimated_tokens > MAX_BUDGET:
            raise HarnessError(f"Token budget exceeded: {estimated_tokens:.0f}/{MAX_BUDGET}")

        # Identical-request guard: the same input at low temperature yields the same rejected
        # output, so a harness path that re-sends it unchanged only burns time. Say so, sample
        # more broadly, and stop the run if it still does not move.
        import hashlib
        key = hashlib.sha256(json.dumps([clean_messages, tools], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        self._identical_repeats = getattr(self, '_identical_repeats', 0) + 1 if key == getattr(self, '_last_request_key', None) else 0
        self._last_request_key = key
        temperature = __import__("runtime_policy").generation_settings()["temperature"]
        if self._identical_repeats >= 4:
            raise HarnessError(f"No progress: the identical model request was sent {self._identical_repeats + 1} times in a row; stopping instead of repeating it")
        if self._identical_repeats:
            note = ("IDENTICAL REQUEST NOTICE: this exact input was already answered " + str(self._identical_repeats)
                    + " time(s) and that answer made no progress. Respond with a materially different action.")
            clean_messages = [dict(m) for m in clean_messages]
            if clean_messages and clean_messages[-1].get("role") == "user" and isinstance(clean_messages[-1].get("content"), str):
                clean_messages[-1]["content"] += "\n" + note
            else:
                clean_messages.append({"role": "user", "content": note})
            temperature = round(min(1.0, max(temperature, 0.6) + 0.15 * self._identical_repeats), 2)

        payload = {
            "model": self.model,
            "messages": clean_messages,
            "tools": tools,
            "tool_choice": "auto" if tools else None,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.95 if thinking_enabled else 0.8,
            "top_k": 20,
            "presence_penalty": 0.0 if thinking_enabled else 1.5,
            "repetition_penalty": 1.0,
            "chat_template_kwargs": {"enable_thinking": thinking_enabled}
        }
        # Remove None values to keep payload clean
        payload = {k: v for k, v in payload.items() if v is not None}

        req = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        try:
            from model_transport import complete
            reply = complete(req, __import__("runtime_policy").generation_settings()["timeout"])
            self.last_finish_reason = (reply.get("choices") or [{}])[0].get("finish_reason")
            return reply
        except urllib.error.HTTPError as e:
            # mlx_lm.server answers 404 with {"error": ...} when generation itself raises (e.g. the
            # chat template rejects the messages); keep that reason and the request for diagnosis.
            try:
                detail = e.read().decode('utf-8', 'replace')[:600]
            except Exception:
                detail = ''
            job = os.environ.get('HARNESS_JOB_DIR')
            if job:
                try:
                    from pathlib import Path as _P
                    _P(job, 'failed-model-request.json').write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
                except OSError:
                    pass
            raise HarnessError(f"LLM connection failed: {e}" + (f" — server said: {detail}" if detail else ""))
        except urllib.error.URLError as e:
            raise HarnessError(f"LLM connection failed: {e}")

class WorkspaceManager:
    def __init__(self, workspace_path):
        self.root = Path(workspace_path).resolve()
        if not self.root.exists():
            raise HarnessError(f"Workspace does not exist: {workspace_path}")

    def safe_path(self, path_str):
        target = (self.root / path_str).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            raise HarnessError(f"Path traversal attempt: {path_str}")
        if '.git' in target.relative_to(self.root).parts:
            raise HarnessError(f"{path_str} is version-control data managed by the platform")
        return target

    # The common system belongs to the framework owner, not to a screen-building run: sign-in, permissions, menus,
    # the shell, the home page, the board and the UI kit. A run that damages them breaks every screen at once.
    # Shared screen parts at the framework root (BusinessWorkspace, RecordGrid, ...) stay editable.
    FRAMEWORK_CORE = ('frontend/src/framework/system/', 'frontend/src/framework/workspace/', 'frontend/src/framework/auth/',
                      'frontend/src/framework/ui/', 'frontend/src/screens/Home.tsx',
                      'backend/src/main/java/com/example/localinventory/framework/')

    def framework_core(self, path):
        if os.environ.get('HARNESS_ALLOW_FRAMEWORK_CORE') == '1':
            return False
        try:
            rel = Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return False
        return any(rel == item or rel.startswith(item) for item in self.FRAMEWORK_CORE)

    def is_protected(self, path):
        # Protect node_modules from writes
        return any(p in path.parts for p in ("node_modules", "harness", "tests", ".git")) or self.framework_core(path)

    def protection_note(self, path):
        if self.framework_core(path):
            return ('공통 시스템 파일입니다(로그인·권한·메뉴·홈·게시판·UI 부품). 화면 작업에서는 고칠 수 없습니다. '
                    '요청은 frontend/src/screens 의 화면 파일이나 새 백엔드 파일로 구현하고, 시스템 이름·로고·배경·메뉴·권한은 '
                    '시스템 설정/메뉴 편성 화면에서 바꾸는 값이라 코드로 건드리지 않습니다.')
        return ''

class Checker:
    # _check_backend always delegates schema application to isolated_backend.
    schema_application_scope = 'fresh-owned'

    def __init__(self, workspace):
        self.workspace = workspace

    def run_check(self, mode):
        if mode == "python":
            return self._check_python()
        elif mode == "frontend":
            return self._check_frontend()
        elif mode == "backend":
            return self._check_backend()
        elif mode == "framework":
            harness_path = Path(__file__).resolve().parent
            browser_script = harness_path / "tests" / "framework_browser.cjs"
            cmd = ["node", str(browser_script), str(self.workspace.root)]
            return self._exec(cmd, cwd=str(self.workspace.root))
        else:
            raise HarnessError(f"Unknown check mode: {mode}")

    def _check_python(self):
        # Run unittest discovery in workspace/tests
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
        return self._exec(cmd, cwd=str(self.workspace.root))

    def _check_frontend(self):
        # tsc --noEmit then vite build
        fe_dir = self.workspace.root / "frontend"
        if not fe_dir.exists():
            return {"success": False, "stdout": "", "stderr": "frontend directory not found"}
        
        from screen_sites import precheck
        broken = precheck(self.workspace.root)   # a standard screen change: every place of a new field is filled in
        if broken:
            return broken
        res1 = self._exec(["npx", "tsc", "--noEmit"], cwd=fe_dir)
        if not res1["success"]: return res1
        
        return self._exec(["npx", "vite", "build"], cwd=fe_dir)

    def _check_backend(self):
        from backend_conventions import check as conventions
        broken = conventions(self.workspace.root)
        if broken:
            return broken
        from isolated_backend import run_backend
        return run_backend(self, self._check_backend_unisolated)

    def _check_backend_unisolated(self):
            # Use trusted maven image with mdi-m2 network, workspace/backend mount, and DB_URL
            backend_dir = self.workspace.root / "backend"
            cmd = [
                "docker", "run", "--rm",
                "--network", "mdi-internal",
                "-v", f"{backend_dir}:/app",
                "-w", "/app",
                "-e", "DB_URL=" + os.environ.get("HARNESS_TEST_DB_URL", "jdbc:postgresql://mdi-db:5432/mdi_local_test"),
                "-v", "mdi-m2:/root/.m2",
                "maven:3.9-eclipse-temurin-17",
                "mvn", "-o", "clean", "test"
            ]
            import shutil
            shutil.rmtree(backend_dir / "target" / "classes", ignore_errors=True)
            result = self._exec(cmd)

            # Identify if result is dict or object and extract values
            if isinstance(result, dict):
                stdout, stderr, exit_code, success = result.get("stdout", ""), result.get("stderr", ""), result.get("exit_code", 0), result.get("success", True)
            else:
                stdout, stderr, exit_code, success = getattr(result, "stdout", ""), getattr(result, "stderr", ""), getattr(result, "exit_code", 0), getattr(result, "success", True)

            # Archive full logs
            log_path = self.workspace.root / "backend" / "target" / "harness-maven.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}")

            # Limit return values
            stdout_lim = stdout[-12000:] if len(stdout) > 12000 else stdout
            stderr_lim = stderr[-12000:] if len(stderr) > 12000 else stderr

            if isinstance(result, dict):
                result["stdout"], result["stderr"] = stdout_lim, stderr_lim
                return result
            else:
                result.stdout, result.stderr = stdout_lim, stderr_lim
                return result

    def _exec(self, cmd, cwd=None):
        try:
            proc = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                cwd=cwd, 
                timeout=120
            )
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode
            }
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1}

class Harness:
    def __init__(self, args):
        self.args = args
        self.workspace = WorkspaceManager(args.workspace)
        self.llm = LocalLLMClient(args.llm_url, args.model)
        self.checker = Checker(self.workspace)
        self.history = []
        self.evidence_path = Path("harness_evidence.log")
        self.ponytail_level = args.ponytail

    def log_event(self, event_type, data):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data
        }
        self.history.append(entry)
        with open(self.evidence_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _compact_history(self, messages, task):
        """
        Compacts messages to fit budget.
        Retains: system message, task, and a valid suffix of recent messages.
        """
        if len(messages) <= 4:
            return messages
        
        # Find the last assistant message that is not the task (index 1)
        last_assistant_idx = -1
        for i in range(len(messages) - 1, 1, -1):
            if messages[i].get('role') == 'assistant':
                last_assistant_idx = i
                break
        
        if last_assistant_idx > 1:
            # Keep system, task, and everything from the last assistant onwards
            # We also include a summary of previous work to prevent re-reading.
            summary_parts = ["Summary of previous work:"]
            for i in range(1, last_assistant_idx):
                if messages[i].get('role') == 'tool':
                    # Only include successful or informative tool results in summary
                    data = messages[i].get('content', '')
                    if len(data) > 1000:
                        data = data[:1000] + "... [truncated]"
                    
                    # Get tool name from previous assistant message
                    tool_name = "unknown"
                    if i > 0 and messages[i-1].get('role') == 'assistant':
                        tc = messages[i-1].get('tool_calls', [{}])[0]
                        tool_name = tc.get('function', {}).get('name', 'tool')
                    
                    summary_parts.append(f"- {tool_name}: {data[:200]}")
            
            summary = "\n".join(summary_parts)
            return [messages[0], messages[1], {"role": "user", "content": summary}] + messages[last_assistant_idx:]
        
        # If no assistant message found, just keep system, task, and last message
        return [messages[0], messages[1], messages[-1]]

    def run(self):
        print(f"Starting harness loop. Task: {self.args.task}")

        system_content = "You are an autonomous developer. Use tools to fix the code until checks pass. When you have finished the task and all checks pass, respond with the word 'finish' or use the 'finish' tool. If you use the 'finish' tool but checks fail, you must continue working."
        skill_path = os.environ.get("PONYTAIL_SKILL_PATH")
        if self.ponytail_level in ("full", "ultra") and skill_path and os.path.exists(skill_path):
            with open(skill_path, "r") as f:
                system_content += f"\n\nPonytail Skill:\n{f.read()}"

        messages = [{"role": "system", "content": system_content}]
        messages.append({"role": "user", "content": self.args.task})

        no_progress_counter = 0

        for round_idx in range(self.args.max_rounds):
            print(f"--- Round {round_idx + 1} ---")

            try:
                # Try to chat. If it fails due to budget, compact and retry once.
                try:
                    response = self.llm.chat(messages, tools=self._get_tool_schemas())
                except HarnessError as e:
                    if "Token budget exceeded" in str(e):
                        print("Budget exceeded. Compacting history...")
                        messages = self._compact_history(messages, self.args.task)
                        response = self.llm.chat(messages, tools=self._get_tool_schemas())
                    else:
                        raise e

                choice = response['choices'][0]['message']
                messages.append(choice)
            except Exception as e:
                print(f"LLM Error: {e}")
                break

            if choice.get('tool_calls'):
                mutation_occurred = False
                for tool_call in choice['tool_calls']:
                    func_name = tool_call['function']['name']
                    args = json.loads(tool_call['function']['arguments'])

                    print(f"Tool: {func_name}({args})")
                    result = self._execute_tool(func_name, args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "content": json.dumps(result)
                    })
                    self.log_event("tool_call", {"name": func_name, "args": args, "result": result})

                    if func_name in ("write_file", "edit_file", "delete_file"):
                        if result.get("status") == "ok" or (result.get("error") is None and "error" not in result):
                            mutation_occurred = True

                    if func_name == "finish":
                        print("Finish tool call detected. Verifying...")
                        all_passed = True
                        for mode in self.args.check.split('|'):
                            res = self.checker.run_check(mode)
                            if not res["success"]:
                                all_passed = False
                                messages.append({"role": "user", "content": f"Verification failed for {mode}: {res['stderr']}"})
                                break

                        if all_passed:
                            print("SUCCESS: All checks passed.")
                            return True
                        else:
                            print("Verification failed. Continuing loop.")

                if mutation_occurred:
                    no_progress_counter = 0
                else:
                    no_progress_counter += 1
            else:
                # If it's not a tool call, it's either 'finish' or just text.
                if "finish" in choice.get('content', '').lower():
                    print("Finish claim detected. Verifying...")
                    all_passed = True
                    for mode in self.args.check.split('|'):
                        res = self.checker.run_check(mode)
                        if not res["success"]:
                            all_passed = False
                            messages.append({"role": "user", "content": f"Verification failed for {mode}: {res['stderr']}"})
                            break

                    if all_passed:
                        print("SUCCESS: All checks passed.")
                        return True
                    else:
                        print("Verification failed. Continuing loop.")
                        continue
                else:
                    no_progress_counter += 1

            if self.args.check:
                for mode in self.args.check.split('|'):
                    print(f"Running check: {mode}")
                    res = self.checker.run_check(mode)
                    status = "PASS" if res["success"] else "FAIL"
                    print(f"Result: {status}")

                    msg = f"Check {mode} result: {status}\nSTDOUT: {res['stdout']}\nSTDERR: {res['stderr']}"
                    # Remove previous checker feedback for the same mode to save context
                    for i in range(len(messages) - 1, -1, -1):
                        if messages[i].get('role') == 'user' and f"Check {mode} result:" in messages[i].get('content', ''):
                            messages.pop(i)
                            break
                    messages.append({"role": "user", "content": msg})
                    self.log_event("check", {"mode": mode, "result": res})

            # Progress nudge
            if no_progress_counter >= 3:
                nudge_msg = (
                    "STOP REPEATING ALREADY READ DOCS OR FILES. "
                    "You have performed several read-only rounds without making any changes. "
                    "Choose one current error and make a small actual source change (write_file, edit_file, or delete_file). "
                    "Then check and continue."
                )
                print(f"!!! PROGRESS NUDGE: {nudge_msg}")
                messages.append({"role": "user", "content": nudge_msg})
                no_progress_counter = 0 # Reset nudge to avoid spamming every round

        print("Reached max rounds or error. Failure.")
        return False

    def _execute_tool(self, name, args):
        try:
            if name == "search_components":
                from component_catalog import search_components
                return search_components(self.workspace.root, args)
            if name == "search_code":
                from code_search import search_code
                return search_code(self.workspace.root, args)
            if name == "list_files":
                path = self.workspace.safe_path(args['path'])
                return {"files": [f.name for f in path.iterdir() if f.name != '.git']}
            elif name == "read_file":
                path = self.workspace.safe_path(args['path'])
                return {"content": path.read_bytes().decode('utf-8')}
            elif name == "write_file":
                path = self.workspace.safe_path(args['path'])
                if self.workspace.is_protected(path):
                    return {"error": f"Write to protected path blocked: {path}. " + self.workspace.protection_note(path)}
                
                # Ensure parent directory exists
                path.parent.mkdir(parents=True, exist_ok=True)
                
                new_content = args['content']
                if path.exists() and path.read_text() == new_content:
                    return {"error": "Content is already identical to target"}
                
                path.write_text(new_content)
                return {"status": "ok"}
            elif name == "edit_file":
                path = self.workspace.safe_path(args['path'])
                if self.workspace.is_protected(path):
                    return {"error": f"Write to protected path blocked: {path}. " + self.workspace.protection_note(path)}
                
                old_text = args['old_text']
                new_text = args['new_text']
                
                if not old_text:
                    return {"error": "old_text cannot be empty", "current_content": path.read_text()}
                if old_text == new_text:
                    return {"error": "old_text and new_text are identical (no-op)", "current_content": path.read_text()}
                
                content = path.read_bytes().decode('utf-8')
                if old_text not in content:
                    return {"error": "old_text not found", "current_content": content}
                
                if content.count(old_text) > 1:
                    return {"error": "ambiguous edit: old_text matches multiple times", "current_content": content}
                
                new_content = content.replace(old_text, new_text)
                path.write_text(new_content)
                return {"status": "ok"}
            elif name == "delete_file":
                path = self.workspace.safe_path(args['path'])
                if self.workspace.is_protected(path):
                    return {"error": f"Delete from protected path blocked: {path}. " + self.workspace.protection_note(path)}
                path.unlink()
                return {"status": "ok"}
            elif name == "astryx_docs":
                topic = args.get("topic", "")
                dep_root = args.get("dependency_root") or os.environ.get("DEPENDENCY_ROOT")
                if dep_root:
                    astryx_bin = Path(dep_root) / ".bin" / "astryx"
                else:
                    astryx_bin = self.workspace.root / "frontend" / "node_modules" / ".bin" / "astryx"
                
                if not astryx_bin.exists():
                    return {"error": f"astryx not found at {astryx_bin}"}
                res = self.checker._exec([str(astryx_bin), "--dense", "--detail", "compact", "component", topic])
                if res["success"]:
                    return {"docs": res["stdout"]}
                return {"error": res["stderr"]}
            elif name == "finish":
                return {"status": "ok"}
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            return {"error": str(e)}

    def _get_tool_schemas(self):
        from code_search import SEARCH_TOOL
        from component_catalog import TOOL as COMPONENT_SEARCH_TOOL
        tools = [
            COMPONENT_SEARCH_TOOL,
            {"type":"function","function":SEARCH_TOOL},
            {"type": "function", "function": {"name": "list_files", "description": "List files", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "read_file", "description": "Read file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "write_file", "description": "Write file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
            {"type": "function", "function": {"name": "edit_file", "description": "Edit file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}}},
            {"type": "function", "function": {"name": "delete_file", "description": "Delete file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "astryx_docs", "description": "Get component docs", "parameters": {"type": "object", "properties": {"topic": {"type": "string"}, "dependency_root": {"type": "string"}}, "required": ["topic"]}}},
            {"type": "function", "function": {"name": "finish", "description": "Call this when the task is complete and all checks pass.", "parameters": {"type": "object", "properties": {}}}}
        ]
        # The design-system docs tool only makes sense for a project that depends on that design system;
        # screens are otherwise built from the project's own framework (frontend/src/framework/API.txt).
        try:
            package = (self.workspace.root / 'frontend/package.json').read_text(encoding='utf-8')
        except OSError:
            package = ''
        if '@astryxdesign' not in package:
            tools = [t for t in tools if t['function']['name'] != 'astryx_docs']
        return tools




def run_task(args):
    import argparse
    from pathlib import Path

    orig_vars = vars(args).copy()
    rounds_done = 0
    last_error_context = ""

    while rounds_done < args.max_rounds:
        remaining = args.max_rounds - rounds_done
        chunk_size = min(8, remaining)

        current_task = orig_vars['task'] if rounds_done == 0 else f"Recover from error: {last_error_context} | Original: {orig_vars['task']}"

        chunk_vars = orig_vars.copy()
        chunk_vars['task'] = current_task
        chunk_vars['max_rounds'] = chunk_size
        chunk_args = argparse.Namespace(**chunk_vars)

        h = Harness(chunk_args)
        success = h.run()
        rounds_done += chunk_size

        if success:
            return True

        # Build recovery text from h.history
        context_parts = []
        latest_checks = {}
        latest_tools = []

        for entry in h.history:
            if entry.get("type") == "check":
                data = entry.get("data", {})
                mode = data.get("mode")
                if mode:
                    res = data.get("result", {})
                    latest_checks[mode] = f"Check {mode}: success={res.get('success')}, stdout={res.get('stdout')}, stderr={res.get('stderr')}"
            elif entry.get("type") == "tool_call":
                tc = entry.get("data", {})
                name = tc.get("name")
                if name:
                    t_args = tc.get("args", {})
                    res_summary = str(tc.get("result"))[:200]
                    safe_args = {k: v for k, v in t_args.items() if k not in ('content', 'old_text', 'new_text')}
                    latest_tools.append(f"Tool {name} {safe_args} -> {res_summary}")

        # Add source snapshots
        paths_to_read = []
        for entry in reversed(h.history):
            if entry.get("type") == "tool_call":
                path = entry.get("data", {}).get("args", {}).get("path")
                if path and path not in paths_to_read:
                    paths_to_read.append(path)
            if len(paths_to_read) >= 3: break

        total_chars = 0
        for p in paths_to_read:
            try:
                content = h.workspace.safe_path(p).read_text()
                if total_chars + len(content) > 12000:
                    context_parts.append(f"{p} (read_file)")
                    continue
                context_parts.append(f"--- {p} ---\n{content}")
                total_chars += len(content)
            except Exception:
                context_parts.append(f"{p} (read error)")

        for mode, msg in latest_checks.items():
            context_parts.append(msg)
        context_parts.extend(latest_tools[-5:])

        if not context_parts:
            last_error_context = "No diagnostics available."
        else:
            last_error_context = "\n".join(context_parts[-10:])

    return False

from tool_extensions import extend_harness, extend_checker
Harness=extend_harness(Harness)
Checker=extend_checker(Checker)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="?", help="Natural language task")
    parser.add_argument("--workspace", help="Path to workspace")
    parser.add_argument("--check", default="python", help="Check modes: python|frontend|backend")
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--llm-url", default=DEFAULT_LLM_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ponytail", choices=["lite", "full", "ultra", "off"], default="full")
    parser.add_argument("--demo", action="store_true", help="Run self-demo")
    args = parser.parse_args()

    if args.demo:
        if args.max_rounds <= 0:
            args.max_rounds = 32
        import tempfile
        import shutil
        demo_dir = Path(tempfile.mkdtemp())
        print(f"--- DEMO STARTING IN {demo_dir} ---")
        (demo_dir / "tests").mkdir()
        (demo_dir / "app.py").write_text("class BrokenApp:\n    def add(self, a, b):\n        return a - b\n")
        (demo_dir / "tests" / "test_app.py").write_text(
            "import unittest\nfrom app import BrokenApp\n"
            "class TestApp(unittest.TestCase):\n    def test_add(self):\n"
            "        self.assertEqual(BrokenApp().add(1, 2), 3)\n"
        )
        args.workspace = str(demo_dir)
        args.task = "Fix the broken app in app.py so that tests pass."
        args.check = "python"
        harness = Harness(args)
        try:
            success = harness.run()
            if success:
                print("--- DEMO SUCCESS ---")
                sys.exit(0)
            else:
                print("--- DEMO FAILED ---")
                sys.exit(1)
        finally:
            shutil.rmtree(demo_dir)

    if not args.workspace or not args.task:
        parser.error("task and --workspace are required unless --demo is used")

    from supervisor import run_supervised
    success = run_supervised(args, Harness)
    sys.exit(0 if success or (getattr(args, "stop_requested", False) and not getattr(args, "stop_cleanup_failed", False)) else 1)
