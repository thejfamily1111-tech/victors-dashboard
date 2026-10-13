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
QQQ_KEYS = tuple(key for key in CONTROLS if key != 'beta_engine_enabled')
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
    acknowledged = ready and online and applied.get('revision') == revision and received is wanted
    service_key = CONTROLS[key][1]
    services = applied.get('services') or {}
    service = services.get(service_key) if isinstance(services, dict) else None
    service = service if isinstance(service, dict) else {}
    process = str(service.get('state', 'UNKNOWN')).upper()
    service_fresh = _fresh(service.get('heartbeat_at'), now)
    acknowledged = acknowledged and (
        service.get('control_revision') == revision or (not wanted and process == 'STOPPED'))
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


def request_change(context, key, enabled):
    """Exactly one fixed control request per click; no orders or shell commands."""
    state = control_state(context.get('envelope'), key)
    if not context.get('client') or state['requested'] is None:
        st.session_state['control_feedback'] = ('error', 'Controls are not connected. No change was sent.')
        return
    try:
        context['client'].request_controls({key: enabled}, expected_revision=state['revision'], request_id=str(uuid4()))
        st.session_state['control_feedback'] = ('info', CONTROLS[key][0]+' '+('ON' if enabled else 'OFF')+' requested. Waiting for the Mac to acknowledge.')
    except Exception as exc:
        st.session_state['control_feedback'] = ('error', _safe_error(exc))


def request_all(context, enabled):
    """One revision and one atomic request for all five existing controls."""
    states = [control_state(context.get('envelope'), key) for key in CONTROLS]
    if (not context.get('client') or any(s['requested'] is None for s in states)
            or (enabled and not all(s['online'] for s in states))):
        st.session_state['control_feedback'] = ('error', 'All-services change unavailable. No change was sent.')
        return
    try:
        context['client'].request_controls({key: enabled for key in CONTROLS},
            expected_revision=states[0]['revision'], request_id=str(uuid4()))
        st.session_state['control_feedback'] = ('info', 'All services '+('ON' if enabled else 'OFF')+
            ' requested together. Waiting for each Mac service to acknowledge. Open positions remain managed.')
    except Exception as exc:
        st.session_state['control_feedback'] = ('error', _safe_error(exc))


def render_master_control(context):
    states = [control_state(context.get('envelope'), key) for key in CONTROLS]
    ready = context.get('client') is not None and all(s['requested'] is not None for s in states)
    all_on = ready and all(s['requested'] is True for s in states)
    all_off = ready and all(s['requested'] is False for s in states)
    enabled = not all_on
    # A mixed selection goes OFF first; the next click enables everything.
    if ready and not all_on and not all_off:
        enabled = False
    st.button('ALL SERVICES · '+('ON' if enabled else 'OFF'), key='control_all_services',
        disabled=not ready or (enabled and not all(s['online'] for s in states)),
        on_click=request_all, args=(context, enabled))
    confirmed = ready and all(s['acknowledged'] for s in states)
    label = 'ON' if all_on else 'OFF' if all_off else 'MIXED' if ready else 'UNAVAILABLE'
    st.caption('All services: '+label+(' · acknowledged' if confirmed else ' · unconfirmed / pending')+
               ' · QQQ trading, QQQ research, overnight research, VIC and Beta. OFF keeps open positions managed.')


def render_connection(context):
    st.markdown('### Control center')
    st.caption('One dashboard for QQQ and Beta Research · Paper only')
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
    keys = QQQ_KEYS if scope == 'qqq' else ('beta_engine_enabled',)
    st.markdown('### QQQ controls' if scope == 'qqq' else '### Beta engine control')
    st.markdown('''<style>
    [data-testid="stVerticalBlockBorderWrapper"] .stButton > button {min-height:3.2rem;font-size:1.05rem;font-weight:700;}
    </style>''', unsafe_allow_html=True)
    for col, key in zip(st.columns(len(keys)), keys):
        with col:
            with st.container(border=True):
                name, _, note = CONTROLS[key]
                state = control_state(context.get('envelope'), key)
                st.markdown('#### '+name)
                getattr(st, state['tone'])(state['label'])
                st.caption(note)
                left, right = st.columns(2)
                disabled = context.get('client') is None or state['requested'] is None
                # Turning OFF remains available while offline; its eventual receipt
                # stays visibly pending. ON is disabled until the Mac is reachable.
                left.button('ON', key='control_on_'+key, type='primary', use_container_width=True,
                            disabled=disabled or not state['online'] or state['requested'] is True,
                            on_click=request_change, args=(context, key, True))
                right.button('OFF', key='control_off_'+key, use_container_width=True,
                             disabled=disabled or state['requested'] is False,
                             on_click=request_change, args=(context, key, False))
                st.caption(state['detail'])
                st.caption('Requested: '+('ON' if state['requested'] is True else 'OFF' if state['requested'] is False else 'Unknown')+
                           ' · Revision '+str(state['revision'] if state['revision'] is not None else '—'))
                st.caption('Service report: '+display_time(state['process_heartbeat']))
