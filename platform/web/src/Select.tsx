import { useEffect, useId, useRef, useState, type ComponentProps } from "react";
import { Selector as LibrarySelector } from "@astryxdesign/core/Selector";

type Option = { value: string; label: string; disabled?: boolean; description?: string };
type Props = { label: string; isLabelHidden?: boolean; value: string; options: Option[]; onChange: (value: string) => void; isDisabled?: boolean;
  size?: "sm" | "md" | "lg"; placement?: ComponentProps<typeof LibrarySelector>["placement"] };

/** The library's dropdown places its list with CSS anchor positioning, which Safari has only from 26 (Safari 18 opened the list at the
 *  top-left corner of the page; the Mac's own pop-up menu opens over its box). Without it, a plain list is hung right under the box. */
const anchored = typeof CSS !== "undefined" && CSS.supports?.("anchor-name: --a") && !window.location.search.includes("plainselect");      // (plainselect: to see the plain list anywhere)

export function Selector(props: Props) {
  if (anchored) return <LibrarySelector {...(props as ComponentProps<typeof LibrarySelector>)} />;
  return <PlainSelector {...props} />;
}

function PlainSelector(props: Props) {
  const id = useId(), box = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false), [at, setAt] = useState(-1), [up, setUp] = useState(false);
  const ROW = 30, SHOWN = 10;      // at most ten rows show; the rest scroll inside the list
  const listHeight = Math.min(props.options.length, SHOWN) * ROW + 10;
  const toggle = () => {
    const rect = box.current?.getBoundingClientRect();
    // opened upward when it would run past the bottom of the window and there is more room above
    if (rect) { const below = window.innerHeight - rect.bottom, above = rect.top; setUp(below < listHeight + 8 && above > below); }
    setOpen(value => !value); setAt(props.options.findIndex(option => option.value === props.value));
  };
  const height = props.size === "sm" ? 28 : 34, chosen = props.options.find(option => option.value === props.value);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const pick = (option: Option) => { if (option.disabled) return; setOpen(false); if (option.value !== props.value) props.onChange(option.value); };
  const key = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") { setOpen(false); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault(); if (!open) { toggle(); return; }
      setAt(index => Math.max(0, Math.min(props.options.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
    }
    if ((event.key === "Enter" || event.key === " ") && open && props.options[at]) { event.preventDefault(); pick(props.options[at]); }
  };
  return <div ref={box} style={{ position: "relative", display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
    {!props.isLabelHidden && <label htmlFor={id} style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{props.label}</label>}
    <button id={id} type="button" aria-haspopup="listbox" aria-expanded={open} aria-label={props.label} disabled={props.isDisabled}
      onClick={toggle} onKeyDown={key}
      style={{ height, padding: "0 28px 0 8px", borderRadius: 6, border: "1px solid var(--color-border-emphasized, var(--color-border))", background: "var(--color-background-surface)",
        color: "var(--color-text-primary)", font: "inherit", fontSize: props.size === "sm" ? 13 : 14, width: "100%", textAlign: "left", cursor: "pointer", position: "relative",
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
      {chosen?.label ?? ""}
      <svg aria-hidden width="12" height="12" viewBox="0 0 12 12" style={{ position: "absolute", right: 9, top: "50%", transform: `translateY(-50%) rotate(${open ? 180 : 0}deg)` }}>
        <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="var(--color-text-secondary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
    </button>
    {open && <ul role="listbox" aria-label={props.label}
      style={{ position: "absolute", ...(up ? { bottom: "100%", marginBottom: 4 } : { top: "100%", marginTop: 4 }), left: 0, right: 0, zIndex: 1000, listStyle: "none", padding: 4, maxHeight: listHeight, overflowY: "auto", boxSizing: "border-box",
        background: "var(--color-background-surface)", border: "1px solid var(--color-border-emphasized, var(--color-border))", borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,.25)" }}>
      {props.options.map((option, index) => <li key={option.value} role="option" aria-selected={option.value === props.value} aria-disabled={option.disabled}
        onMouseEnter={() => setAt(index)} onMouseDown={event => { event.preventDefault(); pick(option); }}
        style={{ height: ROW, boxSizing: "border-box", padding: "6px 8px", borderRadius: 5, fontSize: 13, alignItems: "center", display: "flex", justifyContent: "space-between", gap: 8, cursor: option.disabled ? "default" : "pointer",
          opacity: option.disabled ? 0.45 : 1, background: index === at ? "var(--color-background-muted, rgba(127,127,127,.15))" : "transparent", color: "var(--color-text-primary)" }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{option.label}</span>{option.value === props.value && <span aria-hidden>✓</span>}
      </li>)}
    </ul>}
  </div>;
}
