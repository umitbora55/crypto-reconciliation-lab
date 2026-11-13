"""Conservative scope hints from invalid JSON, never repaired economic inputs."""
from .model import STREAMS, timestamp

REPORT_STREAMS = ('investor', 'platform_custody', 'external_custody')


def known_asset(raw, config):
    value = raw.get('asset')
    return value if isinstance(value, str) and value in config['assets'] else None


def parsed_time(raw, field):
    value = raw.get(field)
    if not isinstance(value, str):
        return None
    try:
        return timestamp(value)
    except ValueError:
        return None


def relevant(raw, config, asset, stream, balance_at, scope=None):
    """Only fields permitted by the recognized kind can narrow a quarantine block."""
    hinted_asset = known_asset(raw, config)
    if hinted_asset is not None and hinted_asset != asset:
        return False
    kind = raw.get('kind')
    if not isinstance(kind, str) or kind not in ('event', 'opening', 'report', 'manifest'):
        return True  # Unknown kind: no stream/time hints are trustworthy.
    if kind in ('event', 'opening'):
        streams = (kind,)  # Rejected stream/scope/balance_at extras cannot reroute events.
    else:
        allowed = REPORT_STREAMS if kind == 'report' else STREAMS
        hint = raw.get('stream')
        streams = (hint,) if isinstance(hint, str) and hint in allowed else allowed
    if stream not in streams:
        return False
    if scope is not None and kind in ('opening', 'report'):
        allowed_scopes = ([*config['investors'], 'platform', 'external'] if kind == 'opening'
                          else config['investors'] if stream == 'investor'
                          else ['platform'] if stream == 'platform_custody' else ['external'])
        hint = raw.get('scope')
        if isinstance(hint, str) and hint in allowed_scopes and hint != scope:
            return False
    if kind == 'event':
        time = parsed_time(raw, 'occurred_at')
        return time is None or config['opening_at'] < time <= balance_at
    if kind in ('opening', 'report'):
        time = parsed_time(raw, 'balance_at')
        target = config['opening_at'] if kind == 'opening' else balance_at
        return time is None or time == target
    start, end = parsed_time(raw, 'coverage_from'), parsed_time(raw, 'coverage_to')
    if start is None or end is None or start > end:
        return True  # An invalid interval cannot establish unrelated coverage.
    target_start = config['opening_at'] if stream in ('opening', 'event') else balance_at
    target_end = config['opening_at'] if stream == 'opening' else balance_at
    return (start, end) == (target_start, target_end)
