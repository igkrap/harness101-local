import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
from batch_edits import batch_arguments
from edit_limits import MAX_SOURCE_CHARS


class BatchEditLimitTests(unittest.TestCase):
    def test_insertions_into_test_file_over_5000_chars(self):
        current='class T {\n'+'  // x\n'*800+'}\n'
        text='  @Test void added() {}\n'*150
        result=batch_arguments({'path':'T.java','blocks':[{'anchor':'class T {\n','text':text,'position':'after'}]},current)
        self.assertGreater(len(result['new_text']),5000)
        self.assertIn('added()',result['new_text'])

    def test_result_over_shared_limit_rejected(self):
        current='a\n'+'b'*(MAX_SOURCE_CHARS-10)
        with self.assertRaisesRegex(ValueError,'exceeds'):
            batch_arguments({'path':'T.java','blocks':[{'anchor':'a\n','text':'x'*100,'position':'after'}]},current)


if __name__=='__main__':
    unittest.main()
