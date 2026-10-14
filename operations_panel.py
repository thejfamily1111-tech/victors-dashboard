"""Authenticated fixed-operation controls; requested state is never a running receipt."""
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st


CONTROLS = {
    'qqq_trading_enabled': ('QQQ trading', 'qqq', 'New QQQ paper entries. Open positions stay managed when OFF.'),
    'qqq_research_enabled': ('QQQ research', 'overnight', 'Daytime QQQ research and scheduled market reviews.'),
    'overnight_research_enabled': ('Overnight research', 'overnight', 'Global-market research and morning briefings.'),
    'vic_enabled': ('VIC', 'vic', 'Shared market direction for the QQQ teams. OFF pauses new QQQ entries.'),
    'beta_engine_enabled': ('Beta engine', 'beta', 'Other-stock research and new paper entries. Open positions stay managed when OFF.'),
}
VIC_KEYS = tuple(key for key in CONTROLS if key != 'beta_engine_enabled')
QQQ_KEYS = VIC_KEYS  # Existing transport keys stay compatible with the Mac controller.
GROUPS = {'master': tuple(CONTROLS), 'vic': VIC_KEYS, 'beta': ('beta_engine_enabled',)}
GROUP_NAMES = {'master': 'Master', 'vic': 'VIC', 'beta': 'Beta Research'}
FRESH_SECONDS = 90
ERRORS = {
    'NOT_CONFIGURED': 'Dashboard controls need the one-time secure connection setup.',
    'UNAUTHORIZED': 'The secure control connection needs attention.',
    'FORBIDDEN': 'The secure control connection needs attention.',
    'CONFLICT': 'Another control change was saved first. Refresh and try again.',
    'REVISION_CONFLICT': 'Another control change was saved first. Refresh and try again.',
    'DEVICE_MISMATCH': 'This dashboard is paired with a different Mac. Controls are unavailable.',
    'NETWORK': 'The control service is temporarily unreachable. No change was confirmed.',
    'TRANSPORT_ERROR': 'The control service is temporarily unreachable. No change was confirmed.',
    'NETWORK_ERROR': 'The control service is temporarily unreachable. No change was confirmed.',
    'AUTH_OR_ACCESS_ERROR': 'The secure control connection needs attention.',
    'RATE_LIMITED': 'The control service is temporarily rate limited. No change was confirmed.',
}


def _timestamp(value):
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (ValueError, TypeError):
        return None


def _fresh(value, now):
    value = _timestamp(value)
    return value is not None and -5 <= (now - value).total_seconds() <= FRESH_SECONDS


def display_time(value):
    from zoneinfo import ZoneInfo
    value = _timestamp(value)
    return value.astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %I:%M:%S %p ET') if value else 'Not received'


def control_state(envelope, key, now=None):
    """Pure status derivation, independent of a Streamlit session or network."""
    now = now or datetime.now(timezone.utc)
    desired = envelope.get('desired') if isinstance(envelope, dict) else None
    applied = envelope.get('applied') if isinstance(envelope, dict) else None
    desired = desired if isinstance(desired, dict) else {}
    applied = applied if isinstance(applied, dict) else {}
    wanted = (desired.get('controls') or {}).get(key)
    received = (applied.get('controls') or {}).get(key)
    revision = desired.get('revision')
    ready = type(wanted) is bool and type(revision) is int and revision >= 0
    online = _fresh(applied.get('observed_at'), now)
    acknowledged = (ready and online and type(applied.get('revision')) is int
                    and applied.get('revision') == revision and received is wanted)
    service_key = CONTROLS[key][1]
    services = applied.get('services') or {}
    service = services.get(service_key) if isinstance(services, dict) else None
    service = service if isinstance(service, dict) else {}
    process = str(service.get('state', 'UNKNOWN')).upper()
    service_fresh = _fresh(service.get('heartbeat_at'), now)
    acknowledged = acknowledged and (
        (type(service.get('control_revision')) is int and service.get('control_revision') == revision)
        or (not wanted and process == 'STOPPED'))
    result = dict(requested=wanted if ready else None, applied=received if type(received) is bool else None,
                  revision=revision, online=online, acknowledged=acknowledged,
                  process=process, service_fresh=service_fresh, updated_at=desired.get('updated_at'),
                  observed_at=applied.get('observed_at'), process_heartbeat=service.get('heartbeat_at'))
    if not ready:
        result.update(label='NOT CONNECTED', tone='warning', detail='No valid control settings have been received.')
    elif not online:
        result.update(label='MAC OFFLINE / UNCONFIRMED', tone='warning', detail='Requested '+('ON' if wanted else 'OFF')+'. Waiting for a fresh Mac receipt.')
    elif not acknowledged:
        result.update(label='CHANGE PENDING', tone='warning', detail='Requested '+('ON' if wanted else 'OFF')+'. The Mac has not acknowledged this revision.')
    elif process == 'ERROR':
        result.update(label='NEEDS ATTENTION', tone='error', detail='The Mac received the setting, but the service reports an error.')
    elif wanted and (process not in {'RUNNING', 'STARTING'} or not service_fresh):
        result.update(label='ON · WAITING FOR SERVICE', tone='warning', detail='Setting acknowledged; current service activity is not yet confirmed.')
    elif wanted and process == 'STARTING':
        result.update(label='STARTING', tone='warning', detail='The Mac is starting this service.')
    elif wanted:
        result.update(label='ON · RUNNING', tone='success', detail='The Mac acknowledged ON and reports a fresh service heartbeat.')
    else:
        monitoring = process == 'RUNNING' and key in {'qqq_trading_enabled', 'beta_engine_enabled'}
        if monitoring and not service_fresh:
            result.update(label='OFF · MONITOR UNCONFIRMED', tone='warning',
                          detail='OFF was acknowledged; the position monitor has no fresh heartbeat.')
        else:
            result.update(label='OFF · POSITION MONITORING' if monitoring else 'OFF', tone='info',
                          detail='New activity is paused; existing positions continue to be managed.' if monitoring else 'The Mac acknowledged OFF.')
    return result


def _safe_error(exc):
    code = getattr(exc, 'code', '')
    return ERRORS.get(code, 'The control request could not be confirmed. Refresh the dashboard before trying again.')


def load_context(d):
    """Read once per page refresh. Secrets stay server-side and never enter UI output."""
    try:
        from control_transport import ControlClient
        settings = {key: d.setting(key, '') for key in (
            'CONTROL_GITHUB_TOKEN', 'CONTROL_DEVICE_ID')}
        client = ControlClient.from_settings(settings, role='operator')
        envelope = client.read_status()
        return {'client': client, 'envelope': envelope, 'error': None}
    except Exception as exc:
        return {'client': None, 'envelope': {}, 'error': _safe_error(exc)}


def group_state(envelope, group, now=None):
    """One visible status only after every component acknowledges the revision."""
    now = now or datetime.now(timezone.utc)
    states = [control_state(envelope, key, now) for key in GROUPS[group]]
    ready = all(state['requested'] is not None for state in states)
    all_on = ready and all(state['requested'] is True for state in states)
    all_off = ready and all(state['requested'] is False for state in states)
    result = {
        'ready': ready, 'requested': True if all_on else False if all_off else None,
        'mixed': ready and not all_on and not all_off,
        'revision': states[0]['revision'], 'online': all(state['online'] for state in states),
        'acknowledged': ready and all(state['acknowledged'] for state in states),
        'states': states,
    }
    wanted = 'ON' if all_on else 'OFF' if all_off else 'MIXED'
    if not ready:
        result.update(label='NOT CONNECTED', tone='warning', detail='No valid control settings have been received.')
    elif not result['online']:
        result.update(label='MAC OFFLINE / UNCONFIRMED', tone='warning',
                      detail='Requested '+wanted+'. Waiting for a fresh Mac receipt.')
    elif not result['acknowledged']:
        result.update(label='CHANGE PENDING', tone='warning',
                      detail='Requested '+wanted+'. Waiting for every component to acknowledge this revision.')
    elif any(state['label'] == 'NEEDS ATTENTION' for state in states):
        result.update(label='NEEDS ATTENTION', tone='error', detail='A component reports an error. Check the Mac service diagnostic.')
    elif result['mixed']:
        result.update(label='MIXED', tone='warning', detail='Some components are ON and some are OFF. Choose ON or OFF to set them together.')
    elif all_on:
        if all(state['label'] == 'ON · RUNNING' for state in states):
            result.update(label='ON · RUNNING', tone='success', detail='Every component acknowledged ON and reports a fresh heartbeat.')
        else:
            result.update(label='ON · WAITING FOR SERVICE', tone='warning',
                          detail='ON was acknowledged; current activity is not yet confirmed for every component.')
    elif any(state['label'] == 'OFF · MONITOR UNCONFIRMED' for state in states):
        result.update(label='OFF · MONITOR UNCONFIRMED', tone='warning', detail='OFF was acknowledged; a position monitor has no fresh heartbeat.')
    elif any(state['label'] == 'OFF · POSITION MONITORING' for state in states):
        result.update(label='OFF · POSITION MONITORING', tone='info', detail='New activity is paused; existing positions continue to be managed.')
    else:
        result.update(label='OFF', tone='info', detail='Every component acknowledged OFF.')
    return result


def request_group(context, group, enabled):
    """Commit the complete group in one revision; stale ON requests never send."""
    state = group_state(context.get('envelope'), group)
    if (type(enabled) is not bool or not context.get('client') or not state['ready']
            or (enabled and not state['online'])):
        st.session_state['control_feedback'] = ('error', GROUP_NAMES[group]+' change unavailable. No change was sent.')
        return
    try:
        context['client'].request_controls({key: enabled for key in GROUPS[group]},
            expected_revision=state['revision'], request_id=str(uuid4()))
        st.session_state['control_feedback'] = ('info', GROUP_NAMES[group]+' '+('ON' if enabled else 'OFF')+
            ' requested. Waiting for the Mac to acknowledge every component. Open positions remain managed.')
    except Exception as exc:
        st.session_state['control_feedback'] = ('error', _safe_error(exc))


def request_all(context, enabled):
    request_group(context, 'master', enabled)


def request_change(context, key, enabled):
    # Retain compatibility for callers while keeping VIC as an atomic group.
    group = 'beta' if key == 'beta_engine_enabled' else 'vic'
    if key not in CONTROLS:
        raise ValueError('Unknown control')
    request_group(context, group, enabled)


def render_master_control(context):
    state = group_state(context.get('envelope'), 'master')
    ready = context.get('client') is not None and state['ready']
    # Mixed selections go OFF first; the next click enables everything.
    enabled = state['requested'] is not True and not state['mixed']
    st.button('MASTER · '+('ON' if enabled else 'OFF'), key='control_all_services',
        disabled=not ready or (enabled and not state['online']),
        on_click=request_all, args=(context, enabled))
    st.caption('Master: '+state['label']+' · Controls VIC and Beta Research together. '+state['detail'])


def render_connection(context):
    st.markdown('### Control center')
    st.caption('One dashboard for VIC and Beta Research · Paper only')
    render_master_control(context)
    if context.get('error'):
        st.warning(context['error'])
    applied = (context.get('envelope') or {}).get('applied') or {}
    online = _fresh(applied.get('observed_at'), datetime.now(timezone.utc))
    if online:
        st.caption('Mac connected · Last receipt '+display_time(applied.get('observed_at')))
    else:
        st.warning('Mac activity is unconfirmed. Last receipt: '+display_time(applied.get('observed_at'))+'.')
    if applied.get('error_code'):
        st.warning('Mac service diagnostic: '+str(applied['error_code']).replace('_',' ').lower()+'. Check each service receipt below.')
    feedback = st.session_state.pop('control_feedback', None)
    if feedback:
        getattr(st, feedback[0])(feedback[1])


def render_controls(context, scope='qqq'):
    group = 'vic' if scope in {'qqq', 'vic'} else 'beta'
    st.markdown('### VIC control' if group == 'vic' else '### Beta Research control')
    st.markdown('''<style>
    [data-testid="stVerticalBlockBorderWrapper"] .stButton > button {min-height:3.2rem;font-size:1.05rem;font-weight:700;}
    </style>''', unsafe_allow_html=True)
    with st.container(border=True):
        state = group_state(context.get('envelope'), group)
        st.markdown('#### '+GROUP_NAMES[group])
        getattr(st, state['tone'])(state['label'])
        st.caption('Trading, scanning, overnight research, news and reports.' if group == 'vic'
                   else 'Independent research and new paper entries.')
        left, right = st.columns(2)
        disabled = context.get('client') is None or not state['ready']
        # OFF remains available offline; receipt stays visibly unconfirmed.
        key = 'vic' if group == 'vic' else 'beta_engine_enabled'
        left.button('ON', key='control_on_'+key, type='primary', use_container_width=True,
                    disabled=disabled or not state['online'] or state['requested'] is True,
                    on_click=request_group, args=(context, group, True))
        right.button('OFF', key='control_off_'+key, use_container_width=True,
                     disabled=disabled or state['requested'] is False,
                     on_click=request_group, args=(context, group, False))
        st.caption(state['detail'])
        requested = 'MIXED' if state['mixed'] else 'ON' if state['requested'] is True else 'OFF' if state['requested'] is False else 'Unknown'
        st.caption('Requested: '+requested+' · Revision '+str(state['revision'] if state['revision'] is not None else '—'))
        for member_key, member in zip(GROUPS[group], state['states']):
            # Components have distinct receipts even though they share one switch.
            label = {'qqq_trading_enabled': 'Trading', 'qqq_research_enabled': 'Research',
                     'overnight_research_enabled': 'Overnight research', 'vic_enabled': 'VIC context',
                     'beta_engine_enabled': 'Beta Research'}[member_key]
            st.caption(label+': '+member['label']+' · '+display_time(member['process_heartbeat']))
