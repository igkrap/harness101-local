import { AuthProvider, AuthGate, useAuth, WorkspaceShell, createScreenRegistry, type ScreenModule } from './framework';
import workspace from './workspace.json';
import { useEffect, useMemo, useState } from 'react';
import type { ScreenRegistry } from './framework/workspace/registry';
import { EntityScreen } from './framework/app/EntityScreen';
import { DocumentScreen } from './framework/app/DocumentScreen';
import { SummaryScreen } from './framework/app/SummaryScreen';
import { DashboardScreen } from './framework/app/DashboardScreen';
import { CalendarScreen } from './framework/app/CalendarScreen';
import { TakeScreen } from './framework/app/TakeScreen';
import { LedgerViewScreen } from './framework/app/LedgerViewScreen';
import { TreeScreen } from './framework/app/TreeScreen';
import { entityOf } from './framework/app/definitions';
import { loadDefinitions, type EntityDefinition } from './framework/app/definitions';

const screens = createScreenRegistry(import.meta.glob('./screens/*.tsx', { eager: true }) as Record<string, ScreenModule>,
  import.meta.glob('./screens/*.tsx', { eager: true, query: '?raw', import: 'default' }) as Record<string, string>);

function AuthenticatedWorkspace() {
  const auth = useAuth();
  // Definition-driven screens: entities defined on the server become screens without any code file.
  // ?drafts=1 also shows unpublished ones to administrators (how a definition is looked at before it is published).
  const [entities, setEntities] = useState<EntityDefinition[]>([]);
  useEffect(() => {
    let active = true;
    void loadDefinitions(new URLSearchParams(window.location.search).has('drafts')).then(value => { if (active) setEntities(value); }).catch(() => {});
    return () => { active = false; };
  }, [auth.user?.username]);
  const available = useMemo(() => {
    const result: ScreenRegistry = {...screens};
    for (const entity of entities) {
      if (result[entity.programCode] || entity.definition.dataOnly) continue;      // data only: no screen (read through other screens)
      result[entity.programCode] = { id: entity.programCode, apis: entity.definition.ledgerView ? ['/api/ledger/'] : entity.definition.take || entity.definition.from ? [`/api/take/${entity.key}`, ...(entity.definition.from ? [`/api/data/${entity.key}`] : [])] : entity.definition.calendar ? [`/api/calendar/${entity.key}`] : entity.definition.tree ? [`/api/tree/${entity.key}`] : entity.definition.over ? [`/api/over/${entity.key}`] : entity.definition.dashboard ? entity.definition.dashboard.panels.map(panel => `/api/summary/${panel.summary}`) : [`${entity.definition.summary ? '/api/summary' : '/api/data'}/${entity.key}`],
        meta: { code: entity.programCode, title: entity.definition.title, icon: 'document', keywords: entity.definition.keywords },
        Component: () => entity.definition.ledgerView ? <LedgerViewScreen entity={entity} /> : entity.definition.take ? <TakeScreen entity={entity} /> : entity.definition.from ? <TakeScreen entity={fromScreen(entity)} /> : entity.definition.calendar ? <CalendarScreen entity={entity} /> : entity.definition.tree ? <TreeScreen entity={entity} /> : entity.definition.over ? <WorkScreenFor entity={entity} /> : entity.definition.dashboard ? <DashboardScreen entity={entity} /> : entity.definition.summary ? <SummaryScreen entity={entity} /> : plainScreen(entity) };
    }
    return result;
  }, [screens, entities]);
  if (!auth.user) return null;
  return <><WorkspaceShell screens={available} initialWorkspace={workspace} user={auth.user} onLogout={auth.signOut} /></>;
}

/** A screen made from an earlier list (from): its own screen queries the earlier records still open in a grid, ticked and saved - the
 *  take-over the framework derives (what is carried by name, what each row asks). Its records are looked after on a screen of their own. */
function fromScreen(entity: EntityDefinition): EntityDefinition {
  const from = entity.definition.from!;
  return { ...entity, definition: { ...entity.definition, take: { entity: entity.key, from: from.entity, statuses: from.statuses, set: Object.fromEntries(from.carry.map(name => [name, name])), lineSet: {}, columns: [], group: null, ask: from.ask } } };
}

/** A screen of records of its own: with a number line, status or lines the document screen, else the plain one. */
function plainScreen(entity: EntityDefinition) {
  return (entity.definition.lines || entity.definition.status || entity.definition.fields.some(field => field.type === 'serial')) ? <DocumentScreen entity={entity} /> : <EntityScreen entity={entity} />;
}

/** A work screen draws the entity it is over, through its own path. */
function WorkScreenFor({ entity }: { entity: EntityDefinition }) {
  const over = entity.definition.over!, base = entityOf(over.entity);
  if (!base) return <div style={{ padding: 24 }}>이 화면이 다루는 자료({over.entity})의 화면이 없습니다.</div>;
  return <DocumentScreen entity={base} over={{ key: entity.key, title: entity.definition.title, statuses: over.statuses, actions: over.actions, edit: over.edit, create: Boolean(over.create), ask: over.ask ?? {} }} />;
}

export default function App() {
  return <AuthProvider><AuthGate><AuthenticatedWorkspace /></AuthGate></AuthProvider>;
}
