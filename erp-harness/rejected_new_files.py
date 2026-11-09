"""Bounded, model-authored failed NEW files; never current-source evidence."""
import json

MAX_SOURCE_CHARS = 18000
MAX_METADATA_CHARS = 4096
MAX_DIAGNOSTIC_CHARS = 5000


class RejectedNewFiles:
    def __init__(self, workspace):
        self.workspace = workspace
        self.files = {}
        self.diagnostic = ''
        self.omitted_paths = 0

    def replace(self, records, diagnostic):
        """Keep only the latest failed transaction, never accumulate attempts."""
        self.files = {}
        self.omitted_paths = 0
        self.diagnostic = str(diagnostic)[:MAX_DIAGNOSTIC_CHARS]
        if len(str(diagnostic)) > MAX_DIAGNOSTIC_CHARS:
            self.diagnostic += '\n[remaining diagnostic omitted]'
        source_size = metadata_size = 0
        for path, record in records.items():
            raw = record.get('expected')
            if record.get('before') is not None or not isinstance(raw, bytes):
                continue
            # Metadata is bounded too, including arbitrarily long/many paths.
            if metadata_size + len(path) + 160 > MAX_METADATA_CHARS:
                self.omitted_paths += 1
                continue
            metadata_size += len(path) + 160
            source = raw.decode('utf-8', 'replace')
            retained = source_size + len(source) <= MAX_SOURCE_CHARS
            self.files[path] = {'source': source if retained else None, 'chars': len(source)}
            if retained:
                source_size += len(source)

    def discard(self, paths):
        for path in paths:
            self.files.pop(path, None)

    def prune(self):
        # Any real entry supersedes the draft, even if subsequently deleted.
        for path in list(self.files):
            try:
                target = self.workspace.safe_path(path)
                if target.exists() or target.is_symlink():
                    self.files.pop(path, None)
            except (OSError, ValueError):
                self.files.pop(path, None)

    def context(self):
        self.prune()
        if not self.files and not self.omitted_paths:
            return ''
        parts = ['REJECTED NEW FILES: latest failed snapshot only; references, not files on disk. '
                 'These sources failed checks and do not authorize edits of existing files.\n',
                 'FAILED ATTEMPT DIAGNOSTIC:\n' + self.diagnostic + '\n']
        for path, record in self.files.items():
            if record['source'] is None:
                parts.append(f'OMITTED REJECTED NEW FILE: {path} ({record["chars"]} chars; whole-source budget).\n')
            else:
                parts.append(f'REJECTED NEW FILE {path} (absent after rollback; complete model-authored source):\n'
                             + record['source'] + '\n')
        if self.omitted_paths:
            parts.append(f'OMITTED REJECTED NEW FILES: {self.omitted_paths} additional paths (metadata budget).\n')
        return ''.join(parts)

    def read(self, path):
        self.prune()
        record = self.files.get(path)
        if record is None:
            return None
        result = {'status': 'rejected_candidate', 'exists': False, 'path': path,
                  'diagnostic': self.diagnostic,
                  'notice': 'Failed model-authored draft, not a workspace read or a passed check. '
                            'A corrected absent file can be created with write_file.'}
        if record['source'] is None:
            result.update(source_omitted=True, chars=record['chars'],
                          content=None, omission='Whole source exceeds retained-source budget.')
        else:
            result['content'] = record['source']
        return result


def compact_draft_reads(messages):
    """The anchor supplies drafts once; historical reads cannot grant access."""
    result = []
    for message in messages:
        if message.get('role') == 'tool':
            try:
                data = json.loads(message.get('content', '{}'))
                if data.get('status') == 'rejected_candidate' and data.get('exists') is False:
                    data.pop('content', None)
                    data.pop('diagnostic', None)
                    data['reference'] = 'Historical draft read only; latest retained snapshot, if any, is in rejected_new_files.'
                    message = {**message, 'content': json.dumps(data, ensure_ascii=False)}
            except (ValueError, TypeError, AttributeError):
                pass
        result.append(message)
    return result
