import json
import hashlib
from pathlib import Path

class cycle_context:
    @staticmethod
    def service(h):
        if not hasattr(h, "_code_intelligence"):
            from code_intelligence import Service
            h._code_intelligence = Service(h.workspace)
        return h._code_intelligence

    @staticmethod
    def is_grid_task(task):
        t = task.lower()
        ko = '그리드' in t and any(x in t for x in ['없는', '누락', '빠진']) and any(x in t for x in ['추가', '넣', '보완'])
        en = 'grid' in t and any(x in t for x in ['missing', 'without']) and any(x in t for x in ['add', 'insert'])
        return ko or en

    @staticmethod
    def structures(runner):
        s = cycle_context.service(runner.h)
        paths = sorted(Path(runner.h.workspace.root).glob("frontend/src/screens/*.tsx"))[:12]
        results = []
        for p in paths:
            try:
                rel = str(p.relative_to(runner.h.workspace.root))
                # Use _ast directly to avoid duplicate read resets in service
                if not s._validate(rel): raise Exception("invalid path")
                ast = s._ast(rel, p.read_text(encoding='utf-8'))
                results.append({"path": rel, "jsx_tags": ast.get("jsx_tags", []), "symbols": ast.get("symbols", []), "diagnostics": ast.get("diagnostics", [])})
            except Exception as e:
                results.append({"path": str(p), "error": str(e)})
        return results

    @staticmethod
    def coverage(runner):
        if not cycle_context.is_grid_task(runner.args.task): return ""
        structs = cycle_context.structures(runner)
        business_screens = []
        missing_grids = []
        for item in structs:
            if "error" in item or item.get("diagnostics"):
                return f"AST Error at {item['path']}: {item.get('error') or item.get('diagnostics')}"
            tags = item["jsx_tags"]
            tags = item["jsx_tags"]
            is_biz = any(t in ["form", "TextInput"] for t in tags)
            if is_biz:
                is_grid = any(t.endswith(("Table", "Grid")) or t in ["DataGrid", "DataTable"] for t in tags)
                if is_grid: business_screens.append(item["path"])
                else: missing_grids.append(item["path"])
        if not missing_grids: return ""
        return f"Missing data tables in: {', '.join(missing_grids)}"

    @staticmethod
    def snapshot(runner):
        from call_budget import snapshot as default_snap
        if not any(m in runner.modes for m in ["frontend", "framework"]): return default_snap(runner)
        
        s = cycle_context.service(runner.h)
        structs = [i for i in cycle_context.structures(runner) if "error" not in i]
        manifest = {i["path"]: i for i in structs}
        
        target, ref = None, None
        if cycle_context.is_grid_task(runner.args.task):
            biz_screens = sorted([i["path"] for i in structs if any(t in ["form", "TextInput"] for t in i["jsx_tags"])])
            missing = [p for p in biz_screens if not any(t.endswith(("Table", "Grid")) or t in ["DataGrid", "DataTable"] for t in next(x["jsx_tags"] for x in structs if x["path"] == p))]
            if missing: target = missing[0]
            ref = next((i["path"] for i in structs if "Table" in "".join(i["jsx_tags"])), None)
        
        if not target: return default_snap(runner)
        
        paths = []
        content_parts = []
        for p, label in [(target, "CURRENT FILE target"), (ref, "REFERENCE EXISTING TABLE reference")]:
            if not p: continue
            txt = s._validate(p).read_text(encoding='utf-8')
            if len(txt) > 9000 or sum(len(x) for x in content_parts) + len(txt) > 14000: continue
            paths.append(p)
            # Prime read hashes
            h_val = hashlib.sha256(txt.encode()).hexdigest()
            if s.read_hashes.get(p) != h_val: s.read_hashes[p] = h_val
            content_parts.append(f"// {label}: {p}\n{txt}")

        combined = "\n".join(content_parts)

        # LSP Diagnostics
        diag_json = ""
        t_txt = s._validate(target).read_text(encoding='utf-8')
        t_hash = hashlib.sha256(t_txt.encode()).hexdigest()
        key = (target, t_hash)
        if not hasattr(runner, "_auto_diagnostics"): runner._auto_diagnostics = {}
        if key not in runner._auto_diagnostics:
            runner._auto_diagnostics[key] = s.run({'path': target, 'action': 'diagnostics'})
        diag_json = json.dumps(runner._auto_diagnostics[key])[:2200]

        # Fingerprint for event
        fp = hashlib.sha256(f"{target}{t_hash}".encode()).hexdigest()
        if not hasattr(runner, "_analysis_key") or runner._analysis_key != fp:
            runner._analysis_key = fp
            runner.h.log_event('autonomy.analysis', {'paths': paths, 'engine': 'AST + LSP', 'model_calls': 0})

        prompt = f"{combined}\n\nMANIFEST: {json.dumps(manifest)[:4500]}\nDIAGNOSTICS: {diag_json}\n\nINSTRUCTIONS: Target file: {target}. Reference file: {ref}. Allsourcealreadyread remains. Use inspect_code for symbols. Apply one atomic edit to implement data query table matching reference API."
        return (prompt, set(paths))
