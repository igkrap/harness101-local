def plan(self) -> None:
    """
    Generates a deterministic initial plan based on the provided task.
    Sets self.steps to a single 'change' step containing the task description.
    Logs the plan event via self.h.log_event.
    """
    self.steps = [{
        'title': self.args.task[:600],
        'kind': 'change'
    }]
    self.h.log_event('autonomy.plan', {
        'steps': self.steps,
        'source': 'deterministic',
        'model_calls': 0
    })
    return None
