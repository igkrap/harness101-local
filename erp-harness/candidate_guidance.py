def repair_mode_instructions(proposal: dict) -> str:
    """
    Returns brief, clear instructions for a model performing incremental repairs
    based on a proposal dictionary containing a list of edits.
    """
    edits = proposal.get("edits", [])
    if not edits:
        return ""

    return (
        "This is an incremental repair of retained operations; follow FAULTY OPERATIONS "
        "and native compiler/AST feedback first; do not reimplement task or reprint "
        "unchanged companions (harness retains them); fix duplicate declarations inside "
        "indicated insertion slot by keeping only NEW bindings not already in CURRENT NODES, "
        "replace existing declarations by their own IDs; add other nodes only if necessary "
        "to wire corrected code. When compiler identifies insertion slot, edit that slot "
        "first instead of repeating panel JSX."
    )


def scope_mode_instructions(runner) -> str:
    """
    Determines the authoritative task from the runner's requirement gate or arguments,
    and returns a scope-limiting instruction string.
    """
    # 1. Safely attempt to retrieve the authoritative task from requirement_gate
    gate = getattr(runner, 'requirement_gate', None)
    contract = {}
    if isinstance(gate, dict):
        contract = getattr(gate, 'contract', {})
    elif hasattr(gate, 'contract'):
        contract = getattr(gate, 'contract', {})

    contract = contract if isinstance(contract, dict) else {}
    task = contract.get('task')

    # 2. Fallback to runner.args.task if not found in contract
    if not task:
        task = getattr(runner.args, 'task', None)

    # 3. Final fallback if task is still None
    if not task:
        task = "Unknown Task"

    # 4. Retrieve the current stage task from runner.args
    current_stage_task = getattr(runner.args, 'task', "Unknown Stage Task")

    # 5. Construct the instruction string
    # The original request governs scope; stage wording cannot expand user goal.
    # For UI/Layout: reuse existing working form/state/API handlers and move controls 
    # instead of creating unrelated CRUD/new backend endpoints.
    instructions = (
        f"ORIGINAL REQUEST: {task}\n"
        f"CURRENT STAGE: {current_stage_task}\n\n"
        "SCOPE INSTRUCTION: The ORIGINAL REQUEST governs the scope of this operation. "
        "The wording of the CURRENT STAGE task cannot be used to expand the user's goal. "
        "For screen layout or rearrangement requests: reuse existing working form/state/API "
        "handlers and move controls instead of creating unrelated CRUD or new backend endpoints. "
        "Preserve all working behavior and implemented API contracts."
    )

    return instructions
