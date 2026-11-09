import json
from pathlib import Path
import subprocess


def identical_bindings(buffer, snapshot):
    result = subprocess.run([buffer.editor.service.node, str(Path(__file__).with_name('identical_candidate_bindings.cjs'))],
                            input=json.dumps({'source': buffer.source}), text=True, capture_output=True, timeout=10, check=True)
    duplicates = json.loads(result.stdout)['duplicates']
    ranges = buffer.editor._snapshots[snapshot['snapshot_id']].ranges
    by_range = {value: key for key, value in ranges.items()}
    return [{'node_id': by_range[(item['start'], item['end'])], 'code': ''} for item in duplicates
            if (item['start'], item['end']) in by_range][:16]
