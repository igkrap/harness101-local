import pathlib
import re
import difflib
from typing import List, Set


def project_files(root: pathlib.Path) -> List[str]:
    """
    Collects specific *.java and *.tsx files based on directory rules.
    Excludes symlinks, node_modules, target, and external paths.
    Returns sorted list of relative POSIX strings (max 80 files).
    """
    if not root.is_dir():
        return []

    collected = set()
    
    # Rules for backend
    java_dir = root / "backend" / "src" / "main" / "java"
    if java_dir.is_dir():
        for p in java_dir.rglob("*.java"):
            if not p.is_symlink():
                # Check for forbidden segments in path
                rel = p.relative_to(root)
                path_str = str(rel).replace("\\", "/")
                if not any(x in path_str for x in ["node_modules", "target", "external"]):
                    collected.add(path_str)

    # Rules for frontend
    fe_src = root / "frontend" / "src"
    be_test_java = root / "backend" / "src" / "test" / "java"
    if be_test_java.is_dir():
        for p in be_test_java.rglob("*.java"):
            if not p.is_symlink() and root.resolve() in p.resolve().parents:
                rel = p.relative_to(root)
                path_str = str(rel).replace("\\", "/")
                if not any(x in path_str for x in ["node_modules", "target", "external"]):
                    collected.add(path_str)
    # Add .ts to frontend
    if fe_src.is_dir():
        for p in fe_src.rglob("*.ts"):
            if not p.is_symlink():
                rel = p.relative_to(root)
                path_str = str(rel).replace("\\", "/")
                if not any(x in path_str for x in ["node_modules", "target", "external"]):
                    collected.add(path_str)
    if fe_src.is_dir():
        # *.tsx files
        for p in fe_src.rglob("*.tsx"):
            if not p.is_symlink():
                rel = p.relative_to(root)
                path_str = str(rel).replace("\\", "/")
                if not any(x in path_str for x in ["node_modules", "target", "external"]):
                    collected.add(path_str)
        
        # workspace.json
        ws_json = fe_src / "workspace.json"
        if ws_json.is_file() and not ws_json.is_symlink():
            rel = ws_json.relative_to(root)
            path_str = str(rel).replace("\\", "/")
            collected.add(path_str)

    for d in ["backend/src/main/resources", "backend/src/test/resources"]:
        res_dir = root / d
        if res_dir.is_dir():
            for p in res_dir.rglob("*"):
                if not p.is_symlink() and p.suffix in (".sql", ".properties"):
                    rel = p.relative_to(root)
                    path_str = str(rel).replace("\\", "/")
                    if not any(x in path_str for x in ["node_modules", "target", "external"]):
                        collected.add(path_str)

    def sort_key(f):
        return (0 if any(x in f for x in ["resources/"]) else 1, f)

    return sorted(list(collected), key=sort_key)[:80]


def project_context(root: pathlib.Path, scope=None) -> str:
    """
    Returns a bounded string (<=6500) containing file paths and REST contracts.
    """
    files = project_files(root)
    frontend = scope is None or any(mode in scope for mode in ('frontend', 'framework'))
    backend = scope is None or 'backend' in scope
    if scope is not None:
        files = [path for path in files if (frontend and path.startswith('frontend/')) or (backend and path.startswith('backend/'))]
    file_list_str = "Files:\n" + "\n".join(files)
    
    contracts = []
    # Find *Controller.java
    controller_pattern = re.compile(r".*Controller\.java$")
    
    # We need to scan the actual files for contracts
    # To avoid I/O writes/subprocess, we only read.
    for f_path in files:
        if controller_pattern.match(f_path):
            full_path = root / f_path
            try:
                content = full_path.read_text(encoding="utf-8")
                contracts.append(f'--- {f_path} ' + content[:2200])
            except Exception:
                continue

    # Cap contracts: each source max 2200, total max 4000
    capped_contracts = []
    current_len = 0
    for c in contracts:
        if len(c) > 2200:
            c = c[:2197] + "..."
        if current_len + len(c) + 1 <= 4000:
            capped_contracts.append(c)
            current_len += len(c) + 1
        else:
            break
    
    contract_str = "API Contracts:\n" + "\n".join(capped_contracts)
    
    ui_conventions = (
        "\nUI Conventions:\n- New screen: frontend/src/screens/<Name>.tsx with 'export const meta={title:'...'} and default function.\n- App discovers screens via glob and menu automatically.\n- Astryx HStack: use hAlign (not justify).\n- SpacingStep: gap/padding integers 0..8.\n- TextInput: onChange first arg IS THE STRING VALUE (never event.target.value); use string directly. For numeric state, render as String(number) and parse with Number(value). Do not use type='number'; use text/password/email only. Use plain Text for messages (no variant prop).\n- TextInput: use isRequired, controlled value/onChange.\n- Submit handlers: must call actual API and handle response; no TODO/log-only handlers.\n- Submit handlers: must call actual API and handle response; no TODO/log-only handlers.\n- For separate screen requests, create a new file, do not modify existing list.\n- Framework component usage (BusinessWorkspace, QueryPanel, RecordGrid, RecordEditor ...): frontend/src/framework/API.txt"
    )
    if not frontend:
        ui_conventions = ''

    # Combine and bound to 6500
    full_context = f"{file_list_str}\n{contract_str}{ui_conventions}"
    api = root / 'frontend/src/framework/API.txt'
    index = root / 'frontend/src/framework/index.ts'
    if frontend and any((root / 'frontend/src').rglob('*.component.json')):
        return (full_context[:5900] + '\nREUSABLE COMPONENT CATALOG: search_components accepts a Korean or English behavior description and returns actual props, source paths, composition dependencies and validation evidence. Automatic retrieval is supplied separately before planning. Reuse appropriate primitives/composites; business templates are compositions, not copied screens. New reusable pieces need a *.component.json descriptor; read an existing descriptor for its schema.')[:6500]
    if frontend and api.is_file() and index.is_file() and not api.is_symlink() and api.resolve().is_relative_to(root.resolve()):
        framework = '\nAVAILABLE LOCAL FRAMEWORK (read the source for additional detail):\n' + api.read_text()[:3400]
        return full_context[:6500 - len(framework)] + framework
    return full_context[:6500]


def missing_path_message(root: pathlib.Path, requested: str) -> str:
    """
    Returns error string with up to 6 actual matching paths using difflib.
    """
    target_name = pathlib.Path(requested).name
    all_files = project_files(root)
    
    # Try to find matches by basename
    matches = [f for f in all_files if pathlib.Path(f).name == target_name]
    
    if not matches:
        # Use difflib for close matches on the full path string
        matches = difflib.get_close_matches(requested, all_files, n=6, cutoff=0.1)
    
    if not matches:
        # If no matches, show first 8 actual files
        return f"Error: '{requested}' does not exist. Available files: {', '.join(all_files[:8])}"
    
    return f"Error: '{requested}' does not exist. Did you mean: {', '.join(matches[:6])}?"


def new_screen_error(root: pathlib.Path, task: str, initial_screens: List[str]) -> str:
    """
    Detects explicit new screen requests and validates if a new file is provided.
    """
    # Regex for Korean or English "new screen" request
    pattern = re.compile(r'(?:새 화면|새로운 화면|신규 화면|별도 화면|화면 하나|화면 한 개|화면을 추가|화면 추가|화면을 새로)|new screen', re.IGNORECASE)
    
    if not pattern.search(task):
        return ""

    # Check if there's a new *.tsx in frontend/src/screens that wasn't in initial_screens
    screen_dir = root / "frontend" / "src" / "screens"
    found_new = False
    
    if screen_dir.is_dir():
        for p in screen_dir.glob("*.tsx"):
            if not p.is_symlink():
                rel_path = str(p.relative_to(root)).replace("\\", "/")
                if rel_path not in initial_screens:
                    # Validate content requirements
                    try:
                        content = p.read_text(encoding="utf-8")
                        if "export const meta" in content and "export default" in content:
                            found_new = True
                            break
                    except Exception:
                        continue

    if not found_new:
        return ("Requested a separate new screen. Create frontend/src/screens/<Name>.tsx "
                "with export const meta and a default component; modifying an existing "
                "screen is insufficient.")
    
    return ""
