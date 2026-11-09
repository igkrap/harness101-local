import json
import subprocess
import shutil
import tempfile
from pathlib import Path

from edit_limits import MAX_SOURCE_CHARS

TOOL = {
    "name": "add_java_methods",
    "description": "Java17 AST insertion of METHODDECLARATIONS inside existing top-level class, preserving all old members, no anchors/ASTIDs/fullfile/class/imports.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "code": {"type": "string"},
            "class_name": {"type": "string"}
        },
        "required": ["path", "code"],
        "additionalProperties": False
    }
}

def method_arguments(inputs: dict, current: str) -> dict:
    """
    Uses a Dockerized Java 17 AST tool to insert new methods into a Java source file.
    """
    path_str = inputs.get("path", "")
    code_str = inputs.get("code", "")
    class_name = inputs.get("class_name")

    if not path_str or not path_str.startswith("backend/src/") or not path_str.endswith(".java"):
        raise ValueError("path must start with 'backend/src/' and end with '.java'")
    if ".." in path_str or path_str.startswith("/"):
        raise ValueError("path must be relative and contain no '..' segments")
    if not code_str:
        raise ValueError("code must be non-empty")
    if len(code_str) > 12000:
        raise ValueError("code exceeds 12000 chars")
    if len(current) > MAX_SOURCE_CHARS:
        raise ValueError("current source exceeds MAX_SOURCE_CHARS")

    path = Path(path_str)
    if not class_name:
        class_name = path.stem
    
    # Strict Java identifier check (ASCII)
    if not class_name.isidentifier() or not class_name.isascii():
        raise ValueError("class_name must be a strict ASCII Java identifier")

    helper = Path(__file__).parent / "java" / "JavaMethodAst.java"
    if not helper.exists():
        raise FileNotFoundError(f"Helper AST tool not found at {helper}")

    docker_bin = shutil.which("docker") or "/Applications/Docker.app/Contents/Resources/bin/docker"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / "Source.java").write_text(current, encoding="utf-8")
        (tmp_path / "Members.java").write_text(code_str, encoding="utf-8")

        cmd = [
            docker_bin, "run", "--rm", "--network", "none",
            "-v", f"{helper.parent.absolute()}:/tool:ro",
            "-v", f"{tmp_path.absolute()}:/input:ro",
            "maven:3.9-eclipse-temurin-17",
            "java", "/tool/JavaMethodAst.java",
            "/input/Source.java", "/input/Members.java", class_name
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Java AST tool failed: {e.stderr.strip()}")
        except subprocess.TimeoutExpired:
            raise ValueError("Java AST tool timed out")

        try:
            resp = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise ValueError(f"Malformed tool response: {proc.stdout}")

        if not resp.get("ok"):
            raise ValueError(f"AST insertion error: {resp.get('error', 'unknown error')}")

        offset = resp["insert_byte"]
        if not (0 <= offset < len(current.encode("utf-8"))):
            raise ValueError(f"Invalid byte offset: {offset}")

        # The tool logic: find the byte position and insert code. 
        # Since we must preserve ALL bytes, we treat the offset as the insertion point.
        # The requirement implies the tool returns the byte index where the new block starts.
        # We reconstruct the string by splitting at the byte offset.
        
        current_bytes = current.encode("utf-8")
        prefix = current_bytes[:offset]
        suffix = current_bytes[offset:]
        
        # The tool logic for 'insert_byte' usually implies the position after the last 
        # existing member or specific AST node. We insert the code block.
        # We use a newline separator to ensure valid syntax if not provided in code.
        new_content_bytes = (b"\n" + code_str.encode("utf-8") + b"\n").strip()
        
        # Re-calculating based on the requirement: "resultbytes=prefix+b'\n'+code.encodeUTF8+b'\n'+suffix"
        # However, the prompt says: "resultbytes=prefix+b'\n'+code.encodeUTF8+b'\n'+suffix; decodeUTF8"
        # We follow the specific instruction for the byte assembly.
        result_bytes = prefix + b"\n" + code_str.encode("utf-8") + b"\n" + suffix
        new_text = result_bytes.decode("utf-8")

        if len(new_text) > MAX_SOURCE_CHARS:
            raise ValueError("Resulting text exceeds MAX_SOURCE_CHARS")

        return {
            "path": path_str,
            "old_text": current,
            "new_text": new_text
        }
