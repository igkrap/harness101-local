import os
import copy

def extend_output(base):
    class OutputRecovery(base):
        def ask(self, messages, tools):
            response = super().ask(messages, tools)
            
            # Safe attribute access for harness compatibility
            h = getattr(self, 'h', None)
            args = getattr(self, 'args', None)
            llm = getattr(h, 'llm', None) if h else None
            last_reason = getattr(llm, 'last_finish_reason', None) if llm else None
            used = getattr(self, 'used', 0)

            if last_reason != 'length':
                return response

            if len(tools or []) == 1 and tools[0].get('function', {}).get('name') == 'replace_ast_fragments':
                self._compact_fragment_output = True
                if h and h.log_event:
                    h.log_event('autonomy.strategy', {'reason': 'truncated_fragments_use_small_deltas',
                        'max_changes': 2, 'max_code_chars': 2400, 'partial_response_applied': False})
                reason = 'AST response exceeded the output limit. No incomplete response was applied. Next action must use at most two small fragments; existing candidate changes remain retained.'
                return {'role': 'assistant', 'content': reason, '_provider_error': reason}

            orig_limit = int(os.environ.get('LOCAL_LLM_MAX_TOKENS', 4096))
            from context_budget import measure
            in_tokens = measure(messages, tools, reserved=512, capacity=32768)['estimated_input_tokens']
            # next_limit = min(orig*2, 12288, 32768 - in - 512)
            next_limit = min(orig_limit * 2, 12288, 32768 - in_tokens - 512)
            
            if next_limit > orig_limit:
                os.environ['LOCAL_LLM_MAX_TOKENS'] = str(next_limit)
                if h and h.log_event:
                    h.log_event('autonomy.strategy', {
                        'reason': 'output_budget_increased',
                        'before': orig_limit, 'after': next_limit, 'input_tokens': in_tokens
                    })

            # Check if retry is warranted: empty content, no tools, budget available
            content = response.get('content', '') or ''
            has_tools = bool(response.get('tool_calls'))
            max_rounds = getattr(args, 'max_rounds', 0) if args else 0
            
            if (not content.strip() and not has_tools and 
                next_limit > orig_limit and (max_rounds <= 0 or used < max_rounds)):
                
                retry_msgs = copy.deepcopy(messages)
                retry_msgs.append({'role': 'user', 'content': (
                    'Previous response exhausted its output budget before returning an actionable answer. '
                    'Keep the same task, requested format and native checks. Return one concise complete '
                    'action or JSON response; do not repeat unchanged code. No extended analysis.'
                )})

                # Re-verify budget for retry messages
                r_in = measure(retry_msgs, tools, reserved=512, capacity=32768)['estimated_input_tokens']
                if r_in + next_limit + 512 <= 32768:
                    old_thinking = os.environ.get('LOCAL_LLM_THINKING')
                    os.environ['LOCAL_LLM_THINKING'] = 'false'
                    try:
                        if h and h.log_event:
                            h.log_event('autonomy.strategy', {
                                'reason': 'empty_truncated_action_retry', 
                                'thinking': False, 'max_tokens': next_limit
                            })
                        response = super().ask(retry_msgs, tools)
                    finally:
                        if old_thinking is None:
                            os.environ.pop('LOCAL_LLM_THINKING', None)
                        else:
                            os.environ['LOCAL_LLM_THINKING'] = old_thinking
            
            return response

    return OutputRecovery
