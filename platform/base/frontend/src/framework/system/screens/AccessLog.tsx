import { useState } from 'react';
import { BusinessWorkspace } from '../../BusinessWorkspace';
import { QueryPanel } from '../../QueryPanel';
import { RecordGrid, type GridColumn } from '../../RecordGrid';
import type { FieldValues } from '../../fields';
import { exportRows, formatDateTime, printRows } from '../../gridExport';
import { storeDate } from '../../format';
import { Select } from '../../ui';
import { adminApi } from '../adminApi';

export const meta = { code: 'SYS0008', title: '접속 기록', icon: 'list', keywords: ['로그', '접속', '사용 기록', '로그인 기록', '이력'] };

type Entry = { id: number; occurredAt: string; username: string; displayName: string; event: string; programCode: string; programName: string; ip: string; detail: string };
type Row = { id: number; time: string; username: string; displayName: string; what: string; program: string; ip: string; detail: string };
const EVENTS: Record<string, string> = { LOGIN: '로그인', LOGIN_FAILED: '로그인 실패', LOGOUT: '로그아웃', SESSION_REPLACED: '중복 접속으로 종료',
  PROGRAM_OPEN: '화면 열기', PASSWORD_CHANGED: '비밀번호 변경' };
const columns: GridColumn<Row>[] = [
  { key: 'time', label: '일시', width: 170, align: 'center' }, { key: 'username', label: '아이디', width: 130 }, { key: 'displayName', label: '이름', width: 150 },
  { key: 'what', label: '구분', width: 150, align: 'center' }, { key: 'program', label: '화면' }, { key: 'ip', label: '접속 주소', width: 140 }, { key: 'detail', label: '비고', width: 160 },
];

/** Who signed in, failed to, signed out, and which screens were opened (newest first, up to 2,000 rows). */
export default function AccessLog() {
  const [rows, setRows] = useState<Row[]>([]);
  async function load(values: FieldValues) {
    const query = new URLSearchParams({ username: values.username ?? '', event: values.event ?? '', from: storeDate(values.from ?? ''), to: storeDate(values.to ?? ''), limit: '2000' });
    const list = await adminApi<Entry[]>(`/api/system/access-logs?${query}`);
    setRows(list.map(entry => ({ id: entry.id, time: formatDateTime(entry.occurredAt), username: entry.username, displayName: entry.displayName,
      what: EVENTS[entry.event] ?? entry.event, program: entry.programCode ? `${entry.programName || entry.programCode} (${entry.programCode})` : '', ip: entry.ip, detail: entry.detail })));
  }
  return <BusinessWorkspace title="접속 기록"
    actions={{ query: { form: 'access-log-query' }, export: { onClick: () => exportRows('접속 기록', columns, rows), disabled: !rows.length },
      print: { onClick: () => printRows('접속 기록', columns, rows), disabled: !rows.length } }}
    query={<QueryPanel formId="access-log-query" onQuery={load} fields={[{ name: 'username', label: '아이디' },
      { name: 'event', label: '구분', render: control => <Select label="구분" value={control.value} onChange={control.onChange}
          options={[{ value: '', label: '전체' }, ...Object.entries(EVENTS).map(([value, label]) => ({ value, label }))]} /> },
      { name: 'from', label: '시작일', type: 'date', placeholder: '2026/01/01' }, { name: 'to', label: '종료일', type: 'date', placeholder: '2026/12/31' }]} />}
    results={<RecordGrid label="접속 기록" rows={rows} columns={columns} keyField="id" />} />;
}
