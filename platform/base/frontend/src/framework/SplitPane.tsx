import { useRef, useState, type ReactNode } from 'react';
import './SplitPane.css';

export type SplitPaneProps = {
  direction?: 'horizontal' | 'vertical';
  primary: ReactNode;
  secondary: ReactNode;
  initialRatio?: number;
  label?: string;
  secondaryCollapsed?: boolean;
  secondaryCollapsedSize?: number;
};

export function SplitPane({ direction = 'horizontal', primary, secondary, initialRatio = 0.5, label = '패널 크기', secondaryCollapsed = false, secondaryCollapsedSize = 38 }: SplitPaneProps) {
  const clamp = (value: number) => Math.max(0.2, Math.min(0.8, Number.isFinite(value) ? value : 0.5));
  const [ratio, setRatio] = useState(() => clamp(initialRatio));
  const host = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const [isDragging, setIsDragging] = useState(false);
  const horizontal = direction === 'horizontal';
  const tracks = secondaryCollapsed ? `minmax(0, 1fr) 0px ${secondaryCollapsedSize}px` : `${ratio}fr 8px ${1 - ratio}fr`;
  function endDrag() { dragging.current = false; setIsDragging(false); }
  return <div ref={host} data-ui="split-pane" style={{ display: 'grid', gridTemplateColumns: horizontal ? tracks : 'minmax(0, 1fr)', gridTemplateRows: horizontal ? 'minmax(0, 1fr)' : tracks, width: '100%', height: '100%', minWidth: 0, minHeight: 0, flex: 1 }}>
    <div style={{ gridColumn: 1, gridRow: 1, minWidth: 0, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>{primary}</div>
    <div className="split-pane__separator" data-dragging={isDragging || undefined} role="separator" hidden={secondaryCollapsed} tabIndex={secondaryCollapsed ? -1 : 0} aria-label={label} aria-orientation={horizontal ? 'vertical' : 'horizontal'} aria-valuemin={20} aria-valuemax={80} aria-valuenow={Math.round(ratio * 100)}
      style={{ gridColumn: horizontal ? 2 : 1, gridRow: horizontal ? 1 : 2, display: secondaryCollapsed ? 'none' : 'block', cursor: horizontal ? 'col-resize' : 'row-resize', touchAction: 'none' }}
      onPointerDown={event => { dragging.current = true; setIsDragging(true); event.currentTarget.setPointerCapture(event.pointerId); }}
      onPointerMove={event => {
        if (!dragging.current || !host.current) return;
        const bounds = host.current.getBoundingClientRect();
        const length = horizontal ? bounds.width : bounds.height;
        if (length > 0) setRatio(clamp(((horizontal ? event.clientX - bounds.left : event.clientY - bounds.top) - 4) / (length - 8)));
      }}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onKeyDown={event => {
        const decrease = horizontal ? 'ArrowLeft' : 'ArrowUp';
        const increase = horizontal ? 'ArrowRight' : 'ArrowDown';
        if (![decrease, increase, 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        setRatio(value => event.key === 'Home' ? 0.2 : event.key === 'End' ? 0.8 : clamp(value + (event.key === increase ? 1 : -1) * (event.shiftKey ? 0.1 : 0.02)));
      }} />
    <div style={{ gridColumn: horizontal ? 3 : 1, gridRow: horizontal ? 1 : 3, minWidth: 0, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>{secondary}</div>
  </div>;
}
