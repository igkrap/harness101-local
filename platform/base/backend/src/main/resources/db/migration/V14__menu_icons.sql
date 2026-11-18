-- Menu icons can be customised: a built-in icon name or an uploaded SVG (data: URL). Empty = default (folder / the screen's icon).
ALTER TABLE sys_menus ADD COLUMN icon TEXT;
ALTER TABLE sys_modules ALTER COLUMN icon TYPE TEXT;
