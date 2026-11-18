import { Icon } from '../ui';

/** Menu icons for the sidebar (Blueprint's icon set). A screen picks one by name: export const meta = { ..., icon: 'box' }. */
const names: Record<string, string> = {
  home: 'home', box: 'box', list: 'list', document: 'document', users: 'people', truck: 'truck', factory: 'office', building: 'office',
  folder: 'folder-close', warehouse: 'archive', chart: 'timeline-bar-chart', calendar: 'calendar', money: 'dollar', settings: 'cog', logout: 'log-out', star: 'star', more: 'more',
};
export const MENU_ICONS = Object.keys(names).filter(name => !['logout', 'star', 'more'].includes(name));

/**
 * name: a built-in icon, or an uploaded vector image as an SVG data: URL. An uploaded image is drawn as a
 * mask in the current text colour, so it follows the sidebar (dark) and the page (light) alike.
 */
export function MenuIcon({ name }: { name: string }) {
  if (name.startsWith('data:image/svg+xml')) {
    const image = `url("${name}") center / contain no-repeat`;
    return <span aria-hidden="true" style={{ display: 'inline-block', width: 18, height: 18, background: 'currentColor', mask: image, WebkitMask: image }} />;
  }
  return <Icon name={names[name] ?? names.document} />;
}
