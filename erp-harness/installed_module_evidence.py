import json
import pathlib
import re


def missing_module_evidence(root, output):
    """Report installed package metadata for unresolved bare imports."""
    root = pathlib.Path(root).resolve()
    records = []
    for module in dict.fromkeys(re.findall(r"Cannot find module ['\"]([^'\"]+)['\"]", output)):
        if not re.fullmatch(r'(?:@[\w.-]+/)?[\w-][\w.-]*(?:/[\w.-]+)*', module):
            continue
        parts = module.split('/')
        package = '/'.join(parts[:2] if module.startswith('@') else parts[:1])
        manifest = root / 'frontend/node_modules' / package / 'package.json'
        try:
            manifest.resolve().relative_to(root)
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            records.append(f'{module}: no installed package manifest at {manifest.relative_to(root)}')
            continue
        exports = data.get('exports')
        if isinstance(exports, dict) and any(k.startswith('.') for k in exports):
            requested = '.' + module[len(package):]
            keys = sorted(k for k in exports if k.startswith('.') and exports[k] is not None)
            exact = requested in keys
            wildcard = any('*' in k and re.fullmatch(re.escape(k).replace(r'\*', '.*'), requested) for k in keys)
            evidence = 'has an export entry; inspect its target and type declarations' if exact or wildcard else 'is absent from the installed exports map'
            direct = [k for k in keys if '/' not in k[2:]]
            shown = []
            for key in direct + [k for k in keys if k not in direct]:
                if len(', '.join(shown + [key])) > 1800:
                    break
                shown.append(key)
            suffix = f' ({len(keys) - len(shown)} additional export keys omitted)' if len(shown) < len(keys) else ''
            records.append(f'{module}: {evidence}. {manifest.relative_to(root)} version={data.get("version", "unknown")}.\nAvailable package export keys: ' + ', '.join(shown) + suffix)
        else:
            records.append(f'{module}: installed package {package} version={data.get("version", "unknown")}, no subpath exports map. types={data.get("types", data.get("typings", "unspecified"))}')
        if len(records) >= 2:
            break
    if not records:
        return ''
    return ('\n\nUNRESOLVED MODULE EVIDENCE:\n' + '\n'.join(records)
            + '\nAn unavailable dependency requires a different actual import or changes to its uses. Repeating its import does not resolve it. Use current installed exports; do not guess a new package path.')
