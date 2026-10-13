"""Session-local, display-only retention of authenticated telemetry.

Original timestamps are never renewed. Retained data cannot grant controls or
trading permission; callers must display the returned warning.
"""
from copy import deepcopy


def retain_report(state, source, fetch):
    if state.get('source') != source:
        state.clear()
        state['source'] = source
    previous = state.get('report')
    try:
        current = fetch()
        if not isinstance(current, dict) or not isinstance(current.get('snapshot'), dict):
            raise ValueError('No report')
        snapshot = current['snapshot']
        old = previous.get('snapshot', {}) if previous else {}
        # The uploader can send a valid envelope with a missing local team file.
        # Keep the complete prior snapshot, not a mixture of different moments.
        if old.get('teams') and not snapshot.get('teams'):
            raise ValueError('Missing team report')
        state['report'] = deepcopy(current)
        state['warning'] = None
        return deepcopy(current)
    except Exception:
        state['warning'] = ('Telemetry update unavailable. Showing the last received report; '
                            'current team activity and positions are unconfirmed.' if previous else
                            'Telemetry unavailable. No successful report has been received in this session.')
        return deepcopy(previous) if previous else None
