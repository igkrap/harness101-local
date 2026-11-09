import re
from ast_editing import editor
from candidate_order import stable_candidate_order
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional

@dataclass
class NodeInfo:
    id: str
    kind: str
    source: str

def order_candidate_nodes(runner, proposal: Dict, catalog: List[Dict], faulty: List[str]) -> Tuple[List[Dict], str]:
    try:
        ed = editor(runner.h)
        info = ed.snapshot(proposal['path'])
        if info.get('snapshot_id') != proposal.get('snapshot_id'):
            return stable_candidate_order(catalog, faulty, set()), ""
        
        snap = ed._snapshots[info['snapshot_id']]
        gate = getattr(getattr(runner, 'requirement_gate', None), 'contract', {})
        reports = getattr(getattr(runner, 'requirement_gate', None), 'last_report', {})
        
        failed_ids = {r['id'] for r in reports.get('results', []) if r.get('status') != 'passed'}
        target_criteria = []
        for c in gate.get('criteria', []):
            if c['id'] in failed_ids:
                target_criteria.append(c)

        def get_testid(selector: str) -> Optional[str]:
            m = re.search(r"\[data-testid=['\"]([^'\"]+)['\"]\]", selector)
            return m.group(1) if m else None

        valid_targets = set()
        for crit in target_criteria:
            tid = get_testid(crit['check'].get('selector', ''))
            if not tid: continue
            
            matches = []
            for item in catalog:
                node_id = item['id']
                if node_id not in snap.nodes: continue
                actual = snap.nodes[node_id]
                start, _ = snap.ranges[node_id]
                
                # Find opening element that contains this node's start
                found_opener = None
                for oid, info_node in snap.nodes.items():
                    if info_node.kind in ('JsxOpeningElement', 'JsxSelfClosingElement'):
                        o_start, o_end = snap.ranges[oid]
                        if o_start <= start < o_end:
                            # Check if actual.source is a descendant (prefix check)
                            if actual.source.startswith(info_node.source):
                                # Verify the opener itself has the testid
                                if f'data-testid="{tid}"' in info_node.source or f"data-testid='{tid}'" in info_node.source:
                                    found_opener = oid
                                    break
                if found_opener:
                    matches.append(node_id)
            
            if len(set(matches)) == 1:
                valid_targets.add(matches[0])

        if not valid_targets:
            return stable_candidate_order(catalog, faulty, set()), ""

        # Priority: 1. Faulty IDs, 2. Valid native targets, 3. Other existing nodes, 4. Append slots
        # We only return existing nodes from catalog that match valid_targets
        ordered_ids = []
        seen = set()
        
        # 1. Faulty IDs that are valid targets
        for fid in faulty:
            if fid in valid_targets and fid not in seen:
                ordered_ids.append(fid)
                seen.add(fid)
        
        # 2. Other valid targets in catalog order
        for item in catalog:
            cid = item['id']
            if cid in valid_targets and cid not in seen:
                ordered_ids.append(cid)
                seen.add(cid)

        hint = f"Map native failures: {', '.join(ordered_ids)}" if ordered_ids else ""
        return stable_candidate_order(catalog, faulty, valid_targets), hint

    except Exception:
        return stable_candidate_order(catalog, faulty, set()), ""
