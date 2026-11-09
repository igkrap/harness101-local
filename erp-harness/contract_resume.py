import json
import requirement_contract

def restore(gate, rc):
    if not isinstance(rc, dict) or not rc.get("source_job") or \
       not isinstance(rc.get("contract"), dict) or not rc.get("contract_hash"):
        raise ValueError("Invalid rc structure")

    task = gate.runner.args.task
    contract = rc["contract"]
    
    if contract.get("task") != task or \
       contract.get("requirements") != requirement_contract.requirements(task):
        raise ValueError("Contract mismatch with task requirements")

    parsed = requirement_contract.validate(task, contract)

    if requirement_contract.digest(contract) != rc["contract_hash"] or \
       requirement_contract.digest(parsed) != rc["contract_hash"]:
        raise ValueError("Contract hash mismatch")

    if any(c.get("check", {}).get("op") == "manual" for c in parsed["criteria"]):
        raise ValueError("Manual check detected in parsed contract")

    contract_hash = rc["contract_hash"]
    gate.frozen_contract = json.dumps(parsed, ensure_ascii=False, sort_keys=True, allow_nan=False)
    gate.contract_hash = contract_hash

    gate.artifact_dir.mkdir(parents=True, exist_ok=True)
    with open(gate.artifact_dir / "contract.json", "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=4)

    gate.runner.h.log_event('requirement.contract', {
        'contract': parsed,
        'contract_hash': contract_hash,
        'artifact_dir': str(gate.artifact_dir),
        'source_job': rc['source_job']
    })
    
    gate.runner.h.log_event('requirement.contract_reused', {
        'source_job': rc['source_job'],
        'contract_hash': contract_hash,
        'model_calls': 0
    })
    return None
