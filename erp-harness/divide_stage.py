import copy
from divide_context import snapshot, packet
from divide_gate import StageGate
from divide_guard import guard


def run_stage(parent, base, harness_class, stage, index, packets, repair_feedback):
    accepted_paths = set()

    class ScopedHarness(harness_class):
        def log_event(self, kind, data):
            payload = copy.deepcopy(data)
            payload.update({
                'stage_id': stage['id'],
                'stage_index': index + 1,
                'scope': 'stage'
            })
            nonlocal accepted_paths
            if kind == 'autonomy.accepted':
                accepted_paths.update(data.get('paths', []))
                parent.division_accepted = True
            
            mapping = {
                'autonomy.plan': 'autonomy.partition_plan',
                'autonomy.step_finished': 'autonomy.partition_finished'
            }
            mapped_kind = mapping.get(kind, kind)
            super().log_event(mapped_kind, payload)

    class Child(base):
        def current_context(self):
            return snapshot(self, stage)

        def plan(self):
            super().plan()
            self.steps[0]['kind'] = 'verify'

        def apply(self, name, inputs, before=None):
            guard(self, stage, name, inputs)
            result = super().apply(name, inputs, before)
            if name in ('apply_ast_edits','write_file','edit_file','apply_edits','apply_insertions','insert_text','delete_file') and self.cp.pending:
                self._division_ast_focus = False
            return result

        def tools(self):
            items = super().tools()
            if stage['domain'] == 'backend':
                exclude = {'astryx_docs', 'apply_ast_edits', 'inspect_code'}
                return [t for t in items if t['function']['name'] not in exclude]
            return items

    task_str = f"Stage {stage['id']}: {stage['instructions']} (Primary Implementation Scope: {', '.join(stage['paths'])}. Task changes belong inside PRIMARY IMPLEMENTATION FILES; other files read for reference are not replacement targets unless needed to preserve integration)"
    check_val = 'backend' if stage['domain'] == 'backend' else '|'.join(
        m for m in parent.modes if m in ('frontend', 'framework')
    )
    
    child_args = copy.copy(parent.args)
    child_args.task = task_str
    child_args.check = check_val
    
    child = Child(child_args, ScopedHarness)
    
    protected = [
        cid for prev in parent.steps[:index] 
        if prev['id'] in packets 
        for cid in prev['criterion_ids']
    ]
    dependencies = [packets[d] for d in stage['depends_on'] if d in packets]
    
    child.requirement_gate = StageGate(
        parent.requirement_gate, 
        child, 
        stage, 
        protected, 
        dependencies, 
        repair_feedback
    )
    child.initial_screens = parent.initial_screens
    child.used = parent.used
    
    parent.cp = child.cp
    
    try:
        ok = child.run()
    finally:
        parent.used = child.used
        svc = getattr(child.h, '_code_intelligence', None)
        if svc is not None:
            svc.close()

    if not ok:
        parent.feedback = child.feedback
        return False, None

    report = child.requirement_gate.last_report
    proof = packet(parent.requirement_gate, accepted_paths, report)
    proof.update({
        'stage_id': stage['id'],
        'title': stage['title'],
        'domain': stage['domain']
    })
    return True, proof
