import pathlib

def screen_reference(root: str, task: str) -> tuple[str, set[pathlib.Path]]:
    """Returns (formatted_text, set_of_relative_paths) for registration context."""
    root_path = pathlib.Path(root).resolve()
    task_lower = task.lower()
    if not any(kw in task_lower for kw in ("등록", "register", "registration")):
        return '', set()

    content_parts = []
    included_paths = set()

    def collect(pattern: str, limit: int, is_total: bool = False) -> int:
        current_total = 0
        found_count = 0
        try:
            for p in root_path.glob(pattern):
                if p.is_symlink() or not p.is_file(): continue
                if is_total and found_count >= limit: break
                if not is_total and found_count >= 1: break
                
                try:
                    text = p.read_text(encoding='utf-8')
                    if not text: continue
                    
                    # Check if file is within root
                    if root_path not in p.resolve().parents and p.resolve() != root_path:
                        continue

                    chunk = text[:limit]
                    if is_total:
                        if current_total + len(chunk) > limit:
                            chunk = chunk[:limit - current_total]
                        current_total += len(chunk)
                    else:
                        current_total = len(chunk)

                    content_parts.append(f"--- FILE: {p.relative_to(root_path)} ---\n{chunk}")
                    included_paths.add(str(p.relative_to(root_path)))
                    found_count += 1
                    if is_total: 
                        if current_total >= limit: break
                except (OSError, UnicodeDecodeError):
                    continue
        except OSError:
            pass
        return found_count

    # Frontend: ONE file, max 5500 chars
    if not collect("frontend/src/framework/API.txt", 5500):
        collect("frontend/src/screens/*[Rr][Ee][Gg][Ii][Ss][Tt][Rr][Aa][Tt][Ii][Oo][Nn]*.[Tt][Ss][Xx]", 5500)
    
    # Backend: Up to 4 files, total 7000 chars
    # Note: glob doesn't support recursive depth easily in one go for specific patterns, 
    # but rglob handles it. We filter for @PostMapping manually.
    try:
        backend_files = []
        for p in root_path.glob("backend/src/main/java/**/*Controller.java"):
            if p.is_symlink() or root_path not in p.resolve().parents and p.resolve() != root_path: continue
            try:
                if "@PostMapping" in p.read_text(encoding='utf-8'):
                    backend_files.append(p)
            except OSError: continue
            if len(backend_files) >= 4: break
        
        total_backend_chars = 0
        for p in backend_files:
            if total_backend_chars >= 7000: break
            try:
                txt = p.read_text(encoding='utf-8')
                take = min(len(txt), 7000 - total_backend_chars)
                content_parts.append(f"--- FILE: {p.relative_to(root_path)} ---\n{txt[:take]}")
                included_paths.add(str(p.relative_to(root_path)))
                total_backend_chars += take
            except OSError: continue
    except OSError: pass

    note = "\nNOTE: registration screens need named export const meta with title and default component; " \
           "use matching EXISTING POST endpoint, fields from that controller; " \
           "example screen is only a UI pattern, do not copy its unrelated fields/endpoint.\n"
    
    full_text = "\n".join(content_parts)
    if len(full_text) + len(note) > 13000:
        full_text = full_text[:12500]
        
    return (full_text + note).strip(), included_paths
