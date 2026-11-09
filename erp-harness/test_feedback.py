import os
import glob
import re
import xml.etree.ElementTree as ET
from datetime import datetime

_LINT_ERROR = re.compile(r'^.*:\d+:\d+ error \S+ .+')
_LINT_WARNING = re.compile(r'^.*:\d+:\d+ warning \S+ .+')


def _compact_error_lines(lines, budget):
    """Keep both the location and diagnostic conclusion of a long error line."""
    lines = list(dict.fromkeys(lines))[:3]
    if not lines:
        return ''
    per_line = max(1, (budget - len(lines)) // len(lines))
    compact = []
    for line in lines:
        if len(line) > per_line:
            left = (per_line - 3) // 2
            line = line[:left] + ' … ' + line[-(per_line - left - 3):]
        compact.append(line)
    return '\n'.join(compact)


def _combined_frontend_feedback(output, detailed):
    lint = [line for line in output.splitlines() if _LINT_ERROR.match(line)]
    if not lint:
        return detailed[:4900]
    compiler = [line for line in output.splitlines() if ': error TS' in line]
    if not compiler:
        return detailed[:4900]
    marker = '\nUse the actual installed declarations'
    _, separator, appendix = detailed.partition(marker)
    # Both groups precede the existing declaration marker, so focused repair
    # receives lint and TypeScript failures within its 1,200-character budget.
    head = ('TypeScript errors:\n' + _compact_error_lines(compiler, 520)
            + '\nESLint errors:\n' + _compact_error_lines(lint, 520))
    if not separator:
        return head
    appendix = separator + appendix
    appendix = appendix.split('\n\nCANDIDATE SOURCE CONTEXT:', 1)[0]
    declaration_marker = '\n\nInstalled API declarations:\n'
    instruction, present, records = appendix.partition(declaration_marker)
    if not present:
        return head
    result = head + instruction + present
    # Append complete records instead of slicing a union/property declaration
    # to make room for the newly retained lint diagnostics.
    blocks = re.split(r'(?=^(?:Project|Installed) declaration )', records, flags=re.MULTILINE)
    omitted = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if len(result) + len(block) + 1 <= 4800:
            result += block + '\n'
        else:
            omitted += 1
    if omitted:
        result += f'{omitted} declaration record(s) omitted to fit feedback budget.'
    return result.rstrip()


def feedback(root, mode, resultdict, started) -> str:
    """
    Generates a feedback report based on test results and JUnit XML reports.
    """
    out = f"[{mode}] "
    stdout = resultdict.get('stdout', '')
    stderr = resultdict.get('stderr', '')
    success = resultdict.get('success', False)
    combined_output = stdout + "\n" + stderr

    if success:
        return f"{out}Success"
    if mode == 'frontend':
        from frontend_type_feedback import enrich
        detailed = enrich(root, combined_output)
        if detailed:
            return out + _combined_frontend_feedback(combined_output, detailed)
        # Warnings remain in raw check evidence; failure feedback reserves its
        # bounded space for fatal errors from both cheap checks.
        lint_count = 0
        filtered = []
        for line in combined_output.splitlines():
            if _LINT_WARNING.match(line):
                continue
            if _LINT_ERROR.match(line):
                lint_count += 1
                if lint_count > 3:
                    continue
            filtered.append(line)
        combined_output = '\n'.join(filtered)
    if mode == 'framework' and 'BROWSER_RUNTIME_ERROR:' in combined_output:
        idx = combined_output.find('BROWSER_RUNTIME_ERROR:')
        return out + combined_output[idx:idx+4500]
    if mode == 'backend':
        from backend_failure import root_failure
        diagnostic = root_failure(root, combined_output, started)
        if diagnostic:
            return out + diagnostic

    # Check for compilation error to decide whether to parse XML
    use_xml = (mode == 'backend' and "COMPILATION ERROR" not in combined_output)

    report_parts = []
    if use_xml:
        report_path = os.path.join(root, "backend/target/surefire-reports/TEST-*.xml")
        xml_files = glob.glob(report_path)
        # Filter by modification time (>= started - 2 seconds)
        freshness_sec = 2
        valid_files = []
        for f in xml_files:
            try:
                mtime = os.path.getmtime(f)
                if mtime >= (started - freshness_sec):
                    valid_files.append(f)
            except OSError:
                continue

        if valid_files:
            summary = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
            msg_map = {}  # message -> {'cases': set(), 'stack': str}

            for f in valid_files:
                try:
                    tree = ET.parse(f)
                    for tc in tree.findall(".//testcase"):
                        summary["tests"] += 1
                        name = f"{tc.get('classname')}.{tc.get('name')}"
                        
                        failure = tc.find('failure')
                        if failure is None:
                            failure = tc.find('error')
                        skipped = tc.find("skipped")

                        if skipped is not None:
                            summary["skipped"] += 1
                        elif failure is not None:
                            if failure.tag == "failure":
                                summary["failures"] += 1
                            else:
                                summary["errors"] += 1
                            
                            msg = failure.text.strip() if failure.text else "Unknown error"
                            # Actual failure message is failure.get('message'), not first stackline
                            msg_line = failure.get('message') or msg.split('\n')[0]
                            if msg_line not in msg_map:
                                msg_map[msg_line] = {"cases": set(), "stack": failure.text or ""}
                            msg_map[msg_line]["cases"].add(name)
                except (ET.ParseError, OSError):
                    continue

            report_parts.append(f"Summary: {summary['tests']} tests, {summary['failures']} failures, {summary['errors']} errors, {summary['skipped']} skipped")
            
            # Sort by message content to prioritize JUnit info
            for msg, data in msg_map.items():
                cases_str = ", ".join(data["cases"])
                report_parts.append(f"{msg} (Cases: {cases_str})")
                stack = data["stack"]
                if stack:
                    # Tail 1200 chars of stack
                    report_parts.append(stack[-1200:])

    # Fallback or supplement with error lines from stdout/stderr
    error_lines = []
    # Patterns: [ERROR], error TS\d+:, Error:, AssertionError:, FAIL:, ERROR:
    pattern = re.compile(r'^(\[ERROR\]|Error:|AssertionError:|FAIL:|ERROR:)', re.MULTILINE)
    ts_pattern = re.compile(r'error TS\d+:')
    
    for line in combined_output.splitlines():
        l_strip = line.strip()
        if pattern.match(l_strip) or ts_pattern.search(l_strip):
            error_lines.append(l_strip)

    # Add last 20 non-empty lines excluding WARN and "Error message = null"
    last_lines = []
    for line in reversed(combined_output.splitlines()):
        l_strip = line.strip()
        if not l_strip: continue
        if "WARN" in l_strip or "Error message = null" in l_strip: continue
        last_lines.append(l_strip)
        if len(last_lines) >= 20: break
    
    report_parts.extend(error_lines)
    report_parts.extend(reversed(last_lines))

    # Join and truncate to 5000 chars
    final_report = out + "\n".join(report_parts)
    return final_report[:5000]
