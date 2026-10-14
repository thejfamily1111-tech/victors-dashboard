"""Render within Victor Terminal's existing authentication and refresh fragment."""
from pathlib import Path
import streamlit as st
from .snapshot import read_local, validate
from .views import age_minutes, timestamp
from .ui import render


def render_beta(d):
    # Never fall back from remote to local: otherwise a cloud user could mistake
    # an unrelated empty ledger for their Mac's portfolio.
    mode = str(d.setting('BETA_DASHBOARD_MODE', d.setting('TELEMETRY_MODE', 'local'))).lower()
    try:
        if mode == 'remote':
            envelope = d.remote_report() or {}
            warning = st.session_state.get('_telemetry_display', {}).get('warning')
            if warning:
                st.warning(warning)
            combined = envelope.get('snapshot') or {}
            snapshot = combined.get('beta')
            source = 'Private Mac telemetry'
            try:
                from .transport import rpc as beta_rpc
                dedicated = beta_rpc(d.setting('TELEMETRY_URL'), d.setting('TELEMETRY_PUBLISHABLE_KEY'),
                                     d.setting('TELEMETRY_READ_TOKEN'))
                if dedicated is not None and (snapshot is None or
                        dedicated['observed_at'] >= snapshot.get('observed_at', '')):
                    snapshot = dedicated
            except ValueError:
                if snapshot is None:
                    st.warning('Beta report connection unavailable. Last upload could not be retrieved.')
            if snapshot is None:
                st.subheader('Beta Research')
                messages = {
                    'BETA_UNAVAILABLE': 'The Mac is connected, but the Beta ledger is unavailable. Check Beta service status above.',
                    'BETA_INVALID': 'The Mac reported a Beta snapshot that could not be validated. Portfolio status is unconfirmed.',
                    'BETA_TOO_LARGE': 'The Beta report exceeded the upload limit. No partial portfolio is shown.',
                }
                if combined.get('beta_error'):
                    st.warning(messages.get(combined['beta_error'], 'Beta telemetry is unavailable.'))
                else:
                    st.info('Waiting for the Mac’s first Beta report. The service controls above show whether its engine is connected.')
                return
            snapshot = validate(snapshot, enforce_limit=False)
        elif mode == 'local':
            project = d.setting('BETA_RESEARCH_DIR', str(Path(d.BASE).parent / 'Beta Research'))
            snapshot = read_local(project, data_dir=d.setting('BETA_DATA_DIR', '') or None)
            source = 'Local Beta ledger (read-only)'
        else:
            raise ValueError('Unsupported Beta dashboard mode')
    except Exception as exc:
        st.subheader('Beta Research')
        st.warning('Beta data is unavailable. The existing dashboard remains available.')
        st.caption('Beta uses the same private Mac connection as the QQQ dashboard. Check the Mac and Beta service status above.')
        st.caption(f'Diagnostic category: {type(exc).__name__}. No credentials are displayed.')
        return
    st.caption(f'{source} · Snapshot: {timestamp(snapshot.get("observed_at"))} · Paper only')
    age = age_minutes(snapshot.get('observed_at'))
    if age is None or age < -1 or age > 2:
        st.warning('Beta telemetry is stale or its clock is invalid. This is a historical snapshot, not confirmed current trading state.')
    try:
        render(snapshot)
    except Exception as exc:
        st.error('A Beta research record could not be displayed. Other dashboard sections remain available.')
        st.caption(f'Diagnostic category: {type(exc).__name__}.')
