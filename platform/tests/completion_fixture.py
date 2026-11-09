"""Isolate editor/recovery unit tests from the independently tested completion gate.

Production completion tests use the real Gate and real HTTP/browser verification.
This dependency stub preserves scripted model replies in older editor unit tests.
"""
class EditorTestGate:
    def __init__(self, runner):
        self.enabled = any(m in ('frontend','framework','backend') for m in runner.modes)
    def prepare(self): pass
    def context(self): return ''
    def verify(self): return {'success':True,'results':[]}
    def inspect(self): return {'measurement_only':True,'layout':[]}
