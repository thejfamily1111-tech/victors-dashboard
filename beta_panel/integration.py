"""Render within Victor Terminal's existing authentication and refresh fragment."""
from pathlib import Path
import streamlit as st
from .snapshot import read_local
from .transport import rpc
from .views import age_minutes, timestamp
from .ui import render


@st.cache_data(ttl=15, show_spinner=False)
def remote(url, key, reader):
    return rpc(url, key, reader)


def render_beta(d):
    # Never fall back from remote to local: otherwise a cloud user could mistake
    # an unrelated empty ledger for their Mac's portfolio.
    mode = str(d.setting('BETA_DASHBOARD_MODE', d.setting('TELEMETRY_MODE', 'local'))).lower()
    try:
        if mode == 'remote':
            snapshot = remote(d.setting('TELEMETRY_URL', ''),
                              d.setting('TELEMETRY_PUBLISHABLE_KEY', ''),
                              d.setting('TELEMETRY_READ_TOKEN', ''))
            source = 'Private Mac telemetry'
            if snapshot is None:
                st.subheader('Beta Research')
                st.info('Waiting for the Beta uploader’s first report. No trading or research process is started by this tab.')
                return
        elif mode == 'local':
            project = d.setting('BETA_RESEARCH_DIR', str(Path(d.BASE).parent / 'Beta Research'))
            snapshot = read_local(project, data_dir=d.setting('BETA_DATA_DIR', '') or None)
            source = 'Local Beta ledger (read-only)'
        else:
            raise ValueError('Unsupported Beta dashboard mode')
    except Exception as exc:
        st.subheader('Beta Research')
        st.warning('Beta data is unavailable. The existing dashboard remains available.')
        st.caption('For a Mac dashboard, set BETA_RESEARCH_DIR to the existing folder. For the website, apply BETA_TELEMETRY_SETUP.sql and start the separate Beta uploader on the Mac.')
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
