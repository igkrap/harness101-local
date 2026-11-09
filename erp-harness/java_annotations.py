import re

def annotation_arguments(inputs, current):
    path = inputs.get('path')
    annotations = inputs.get('annotations')

    if not isinstance(path, str) or not isinstance(annotations, list):
        raise ValueError("Invalid input types")
    if not (1 <= len(annotations) <= 8):
        raise ValueError("Annotation count must be 1-8")

    normalized_annotations = []
    current_lines = current.splitlines()

    for ann in annotations:
        if not isinstance(ann, str) or not (0 < len(ann) <= 1000):
            raise ValueError("Invalid annotation string")
        if '\n' in ann or '\r' in ann:
            raise ValueError("No newlines allowed in annotation")

        clean = ann.lstrip('@')
        type_part = clean.split('(')[0]
        if '.' not in type_part:
            raise ValueError("Type part must contain '.'")

        normalized = '@' + clean
        if normalized in normalized_annotations or normalized in current_lines:
            raise ValueError("Duplicate annotation detected")
        
        normalized_annotations.append(normalized)

    class_lines = [line for line in current_lines if re.match(r'^(?:public\s+)?(?:final\s+)?class\s+\w+', line)]
    if len(class_lines) != 1:
        raise ValueError("Exactly one class declaration required")

    anchor = class_lines[0]
    new_text = '\n'.join(normalized_annotations) + '\n' + anchor

    return {
        'path': path,
        'old_text': anchor,
        'new_text': new_text
    }

ANNOTATION_TOOL = {
    'name': 'add_java_annotations',
    'description': 'Preferred for Java/Spring class annotations such as transactional test isolation and scoped SQL setup. Adds fully qualified annotations BEFORE the class while preserving every existing import and body line. No import edits needed. Provide ALL required annotations together.',
    'parameters': {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'The file path to the Java source file.'
            },
            'annotations': {
                'type': 'array',
                'items': {
                    'type': 'string'
                },
                'minItems': 1,
                'maxItems': 8,
                'description': 'An array of 1 to 8 fully qualified Java annotations to prepend to the class definition.'
            }
        },
        'required': [
            'path',
            'annotations'
        ]
    }
}
