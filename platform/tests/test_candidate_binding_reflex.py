import json
from pathlib import Path
import shutil
import subprocess
import unittest


class CandidateBindingReflexTests(unittest.TestCase):
    def duplicates(self, source):
        script = Path(__file__).resolve().parents[1] / 'identical_candidate_bindings.cjs'
        result = subprocess.run([shutil.which('node') or '/Users/igkrap/.nvm/versions/node/v22.15.0/bin/node', str(script)],
                                input=json.dumps({'source': source}), capture_output=True, text=True, check=True)
        return json.loads(result.stdout)['duplicates']

    def test_identical_react_state_and_callback_duplicates_have_exact_unicode_byte_ranges(self):
        source = 'import {useState} from "react"; function App(){/* 한글 😀 */const [a,setA]=useState({value:1});const f=()=>a;const [a,setA]=useState({value:1});const f=()=>a;return null;}'
        records = self.duplicates(source)
        self.assertEqual(len(records), 2)
        self.assertEqual([source.encode()[r['start']:r['end']].decode() for r in records], ['const [a,setA]=useState({value:1});', 'const f=()=>a;'])

    def test_distinct_scopes_states_and_initial_values_are_preserved(self):
        for source in ['function A(){const x=1;}function B(){const x=1;}', 'const x=1;const x=2;', 'import {useState} from "react";function A(){const [a,setA]=useState(0);const [b,setB]=useState(0);}']:
            with self.subTest(source=source):
                self.assertEqual(self.duplicates(source), [])

    def test_side_effect_initializers_var_and_lazy_state_initializers_are_preserved(self):
        for source in ['const x=run();const x=run();', 'var x=1;var x=1;', 'import {useState} from "react";function A(){const [a,setA]=useState(()=>run());const [a,setA]=useState(()=>run());}', 'const x={get value(){return run()}};const x={get value(){return run()}};']:
            with self.subTest(source=source):
                self.assertEqual(self.duplicates(source), [])
