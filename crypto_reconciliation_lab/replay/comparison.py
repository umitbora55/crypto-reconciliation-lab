"""Full canonical equality with bounded deterministic, typed diagnostics."""
from ..execution.common import canonical
from .common import MAX_DIFFS, MAX_PREVIEW


_MISSING = object()


def _type(value):
    if value is _MISSING:
        return 'missing'
    return {dict: 'object', list: 'array', str: 'string', int: 'integer',
            float: 'number', bool: 'boolean', type(None): 'null'}[type(value)]


def _preview(value):
    if value is _MISSING:
        return None
    if type(value) is dict:
        return 'object with ' + str(len(value)) + ' members'
    if type(value) is list:
        return 'array with ' + str(len(value)) + ' entries'
    # Avoid allocating a second full serialized copy of a long diagnostic string.
    text = value if type(value) is str else canonical(value).decode('ascii')
    return text[:MAX_PREVIEW]


def _pointer(path, key):
    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')


def compare_payloads(saved, recomputed):
    """Walk every difference even after the retained diagnostic list is full."""
    equal = canonical(saved) == canonical(recomputed)
    differences, total = [], 0
    stack = [('', saved, recomputed)]
    while stack:
        path, left, right = stack.pop()
        if left is _MISSING or right is _MISSING:
            kind = 'MISSING_SAVED' if left is _MISSING else 'MISSING_RECOMPUTED'
        elif type(left) is not type(right):
            kind = 'TYPE'
        elif type(left) is dict:
            for key in reversed(sorted(set(left) | set(right))):
                stack.append((_pointer(path, key), left.get(key, _MISSING), right.get(key, _MISSING)))
            continue
        elif type(left) is list:
            for index in reversed(range(max(len(left), len(right)))):
                stack.append((_pointer(path, index), left[index] if index < len(left) else _MISSING,
                              right[index] if index < len(right) else _MISSING))
            continue
        elif canonical(left) != canonical(right):
            kind = 'VALUE'
        else:
            continue
        total += 1
        if len(differences) < MAX_DIFFS:
            differences.append({'path': path, 'kind': kind, 'saved_type': _type(left),
                                'recomputed_type': _type(right), 'saved_preview': _preview(left),
                                'recomputed_preview': _preview(right)})
    # Canonical equality is the authoritative comparison, never a capped list.
    differences.sort(key=lambda item: item['path'])
    return {'state': 'EQUAL' if equal else 'DIFFERENT', 'equal': equal,
            'total_differences': total, 'reported_differences': len(differences),
            'truncated': total > len(differences), 'differences': differences}
