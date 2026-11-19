import { useId, type ComponentProps } from "react";
import { Selector as LibrarySelector } from "@astryxdesign/core/Selector";

type Option = { value: string; label: string; disabled?: boolean; description?: string };
type Props = { label: string; isLabelHidden?: boolean; value: string; options: Option[]; onChange: (value: string) => void; isDisabled?: boolean;
  size?: "sm" | "md" | "lg"; placement?: ComponentProps<typeof LibrarySelector>["placement"] };

/** The library's dropdown places its list with CSS anchor positioning, which Safari has only from 26: there (Safari 18 opened the list
 *  at the top-left corner of the page) the browser's own dropdown is used, which every browser places at its box. */
const anchored = typeof CSS !== "undefined" && CSS.supports?.("anchor-name: --a");

export function Selector(props: Props) {
  const id = useId();
  if (anchored) return <LibrarySelector {...(props as ComponentProps<typeof LibrarySelector>)} />;
  const height = props.size === "sm" ? 28 : 34;
  return <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
    {!props.isLabelHidden && <label htmlFor={id} style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{props.label}</label>}
    <select id={id} aria-label={props.label} value={props.value} disabled={props.isDisabled} onChange={e => props.onChange(e.target.value)}
      style={{ height, padding: "0 8px", borderRadius: 6, border: "1px solid var(--color-border-emphasized, var(--color-border))", background: "var(--color-background-surface)",
        color: "var(--color-text-primary)", font: "inherit", fontSize: props.size === "sm" ? 13 : 14, width: "100%", minWidth: 0 }}>
      {props.options.map(option => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}
    </select>
  </div>;
}
