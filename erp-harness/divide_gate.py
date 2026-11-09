import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Set


class StageGate:
    def __init__(
        self,
        parent_gate: Any,
        child: Any,
        stage: Dict[str, Any],
        protected_ids: List[str],
        packets: List[Dict[str, Any]],
        repair_feedback: str = ""
    ):
        self.parent_gate = parent_gate
        self.child = child
        self.stage = stage
        self.protected_ids = protected_ids
        self.packets = packets
        self.repair_feedback = repair_feedback
        self.enabled = True
        self.last_report = {}
        self.contract = json.loads(parent_gate.frozen_contract)

    def prepare(self) -> None:
        return None

    def selected(self) -> List[Dict[str, Any]]:
        ids: Set[str] = set(self.stage["criterion_ids"]) | set(self.protected_ids)
        return [c for c in self.contract["criteria"] if c["id"] in ids]

    def context(self) -> str:
        scope = {
            "scope": "stage",
            "original_task": self.contract["task"],
            "contract_hash": self.parent_gate.contract_hash,
            "stage": self.stage,
            "criteria": self.selected(),
            "dependency_evidence": self.packets,
            "repair_feedback": self.repair_feedback,
            "rule": (
                "This is a partial stage. Preserve previously verified conditions. "
                "Full goal is verified later. Activate target screen through "
                "frontend/src/workspace.json before UI verification."
            ),
        }
        scope['unresolved_checks'] = [
            {
                'id': r.get('id'),
                'status': r.get('status'),
                'reason': str(r.get('reason', ''))[:2000],
                'evidence': str(r.get('evidence', ''))[:1500]
            }
            for r in getattr(self, 'last_report', {}).get('results', [])
            if r.get('status') != 'passed'
        ][:12]
        scope['feedback_rule'] = 'These latest native requirement failures remain unresolved across tool errors, builds and context refreshes until a new native verification passes. Fix actual behavior/layout, do not resubmit identical source. Build success alone does not clear requirement failures.'
        return json.dumps(scope, ensure_ascii=False)

    def verify(self) -> Dict[str, Any]:
        criteria = self.selected()
        raw = self.parent_gate._probe(criteria)
        
        expected = [c["id"] for c in criteria]
        results = raw.get("results", [])
        actual = [r.get("id") for r in results]

        success = (
            raw.get("success") is True
            and len(expected) > 0
            and sorted(actual) == sorted(expected)
            and len(set(actual)) == len(actual)
            and all(r.get("status") == "passed" for r in results)
        )

        full = raw.copy()
        full.update({
            "success": success,
            "scope": "stage",
            "stage_id": self.stage["id"],
            "contract_hash": self.parent_gate.contract_hash,
            "owned_criterion_ids": self.stage["criterion_ids"],
            "protected_criterion_ids": self.protected_ids,
        })

        report_dir = self.parent_gate.artifact_dir / "stages" / self.stage["id"]
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{uuid.uuid4().hex}-report.json"
        
        full["report_path"] = str(report_path)
        full_to_save = full.copy()
        full_to_save["report_path"] = str(report_path)
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(full_to_save, f, ensure_ascii=False)

        concise = {k: v for k, v in full.items() if k not in ("layout", "screenshot")}
        self.last_report = concise
        self.child.h.log_event("autonomy.stage_verified", concise)
        
        return concise

    def inspect(self) -> Dict[str, Any]:
        data = self.parent_gate.inspect()
        data.update({
            "scope": "stage",
            "stage_id": self.stage["id"]
        })
        return data
