import { StatusBadge } from "./StatusBadge";
import { VStack, HStack } from '@astryxdesign/core/Layout';
import { Heading, Text } from '@astryxdesign/core/Text';
import { Card } from '@astryxdesign/core/Card';
import { Button } from '@astryxdesign/core/Button';
import { ChangesPanel } from './ChangesPanel';
import { FailurePanel } from './FailurePanel';
import type { RunRecord } from './HistoryViews';
const labels:Record<string,string>={succeeded:'성공',failed:'실패',running:'실행 중',stopping:'중지 중',stopped:'중지됨',interrupted:'종료 확인 필요'};
export function LatestResult({job,refreshKey,onSelect}:{job?:RunRecord|null;refreshKey?:number;onSelect:(job:RunRecord)=>void}){
  const legacy=job?.kind==='agent'&&job.status==='succeeded'&&!job.completion_policy;
  const color=job?.status==='succeeded'?'var(--color-text-success)':job?.status==='failed'?'var(--color-text-error)':'var(--color-text-secondary)';
  return <Card padding={5} role="region" aria-label="마지막 실행 결과"><VStack gap={4}>
    <HStack hAlign="between" gap={3}><Heading level={3}>마지막 실행 결과</Heading>{job&&<StatusBadge value={legacy?'unknown':job.status} label={legacy?'기존 성공 판정':labels[job.status]||job.status}/>}</HStack>
    {!job?<Text color="secondary">아직 실행한 작업이 없습니다.</Text>:<>
      <Text weight="bold">{job.goal}</Text>
      <Text color="secondary">{job.id.slice(0,8)} · {new Date(job.finished_at||job.started_at).toLocaleString('ko-KR')}</Text>
      {legacy&&<Text color="secondary">완료 조건 검증 도입 전 기록입니다. 요청 달성 여부는 확인되지 않았습니다.</Text>}
      {job.status==='succeeded'&&<ChangesPanel key={job.id} jobId={job.id} refreshKey={refreshKey} embedded autoOpen/>}
      {['failed','interrupted'].includes(job.status)&&<FailurePanel key={job.id} jobId={job.id} refreshKey={job.status} embedded/>}
      {['running','stopping'].includes(job.status)&&<Text color="secondary">실행이 끝나면 결과를 표시합니다.</Text>}
      {job.status==='stopped'&&<Text color="secondary">실행이 중지됐습니다.</Text>}
      <HStack><Button label="실행 보기" size="sm" variant="secondary" onClick={()=>onSelect(job)}/></HStack>
    </>}
  </VStack></Card>;
}
