import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'erp-harness'))
import screen_sites as ss

SCREEN = '''type CompanyRow = { id: string; companyName: string; updatedAt: string };

const editFields: FieldDefinition[] = [
  { name: 'companyName', label: '회사명', required: true, group: 'basic' },
];

const gridColumns: GridColumn<CompanyRow>[] = [
  { key: 'companyName', label: '회사명', width: 180 },
];

function toRow(data: Record<string, unknown>): CompanyRow {
  return { id: text(data.id), companyName: text(data.companyName), updatedAt: text(data.updatedAt) };
}

export default function Company() {
  async function handleSave(values: FieldValues) {
    const payload = { companyName: values.companyName.trim() };
  }
}
'''
FAX = {'name': 'fax', 'label': '팩스번호', 'required': False, 'sample': '02'}


class ScreenSitesTests(unittest.TestCase):
    def test_every_place_of_a_new_field_is_listed_with_its_line(self):
        steps = ss.plan(SCREEN, [FAX])
        self.assertEqual(len(steps), 5)
        self.assertIn('1행 행 타입', steps[0])
        self.assertIn("`fax: text(data.fax),`", steps[3])
        self.assertIn('payload', steps[4])

    def test_a_partial_edit_names_exactly_the_places_still_missing(self):
        partial = SCREEN.replace('companyName: string;', 'companyName: string; fax: string;').replace("required: true, group: 'basic' },", "required: true, group: 'basic' },\n  { name: 'fax', label: '팩스번호', group: 'extra' },")
        self.assertEqual(ss.missing(partial, FAX), ['grid_columns', 'to_row', 'payload'])

    def test_precheck_fails_until_all_places_are_filled(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'Company.tsx'
            file.write_text(SCREEN, encoding='utf-8')
            ss.expect('Company.tsx', [FAX]); self.addCleanup(ss.EXPECTED.clear)
            result = ss.precheck(folder)
            self.assertFalse(result['success'])
            self.assertIn('toRow', result['stderr'])
            done = SCREEN.replace('companyName: string;', 'companyName: string; fax: string;').replace("group: 'basic' },", "group: 'basic' },\n  { name: 'fax', label: '팩스번호', group: 'extra' },") \
                .replace("width: 180 },", "width: 180 },\n  { key: 'fax', label: '팩스번호', width: 130 },").replace('companyName: text(data.companyName),', 'companyName: text(data.companyName), fax: text(data.fax),') \
                .replace('companyName: values.companyName.trim() }', 'companyName: values.companyName.trim(), fax: values.fax.trim() || null }')
            file.write_text(done, encoding='utf-8')
            self.assertIsNone(ss.precheck(folder))

    def test_required_change_points_at_the_field_line(self):
        steps = ss.plan(SCREEN, [], changed=[{'name': 'companyName', 'label': '회사명', 'required': False, 'sample': 'x'}])
        self.assertIn('4행 편집 필드 회사명', steps[0])


if __name__ == '__main__':
    unittest.main()
