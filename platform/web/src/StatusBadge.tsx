import { Badge, type BadgeVariant } from '@astryxdesign/core/Badge';
const labels:Record<string,string>={running:'실행 중',pending:'진행 중',waiting:'대기',idle:'대기',stopping:'중지 중',stopped:'중지됨',succeeded:'성공',passed:'통과',failed:'실패',interrupted:'확인 필요',unknown:'미검사',stale:'재검사 필요',model:'모델 응답 대기',tool:'도구 실행 중',check:'검사 중'};
const variants:Record<string,BadgeVariant>={running:'info',pending:'info',model:'info',tool:'info',check:'info',succeeded:'success',passed:'success',failed:'error',stopping:'warning',interrupted:'warning',stale:'warning'};
export function StatusBadge({value,label}:{value:string;label?:string}){return <Badge label={label||labels[value]||value} variant={variants[value]||'neutral'} className="status-badge"/>;}
