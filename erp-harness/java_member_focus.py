import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import java_methods
from java_member_request import focused

def extend_java_members(base: Any) -> type:

    class JavaMemberFocusRunner(base):

        def tools(self) -> List[Dict[str, Any]]:
            tools = super().tools()
            if 'backend' in self.modes:
                if not any((t.get('function', {}).get('name') == 'add_java_methods' for t in tools)):
                    tools.append({'type': 'function', 'function': java_methods.TOOL})
            return tools

        def apply(self, name: str, inputs: Dict[str, Any], before: bool) -> Any:
            if name == 'add_java_methods':
                path = self.h.workspace.safe_path(inputs['path'])
                current = path.read_text(encoding='utf-8')
                converted = java_methods.method_arguments(inputs, current)
                return super().apply('apply_edits', {'path': converted['path'], 'edits': [{'old_text': converted['old_text'], 'new_text': converted['new_text']}]}, before)
            return super().apply(name, inputs, before)

        def ask(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]=None) -> Dict[str, Any]:
            callback = lambda m, t: super(JavaMemberFocusRunner, self).ask(m, t)
            resolution = focused(self, messages, callback)
            if resolution is not None:
                return resolution
            return super().ask(messages, tools)
    return JavaMemberFocusRunner
