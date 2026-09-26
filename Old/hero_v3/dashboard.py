"""Read-only production dashboard. No broker, strategy, or data-provider imports."""
from pathlib import Path
import json
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent

def load_snapshot(path=BASE / 'bot_telemetry.json'):
    payload = json.loads(Path(path).read_text())
    if payload.get('schema_version') != 3: 
        raise ValueError('Legacy telemetry: start HERO v3 first')
    return payload

def main():
    import streamlit as st
    import plotly.graph_objects as go
    import pandas as pd
    from streamlit_autorefresh import st_autorefresh
    
    st.set_page_config(page_title='HERO / VIC / LEARN', page_icon='⚡', layout='wide')
    st_autorefresh(interval=15000, key='heartbeat')
    
    st.title('⚡ HERO / VIC / LEARN')
    st.caption('Paper trading • production decisions • read only')
    
    try: 
        data = load_snapshot()
    except (OSError, ValueError) as exc:
        st.warning(str(exc))
        return
        
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(data['heartbeat'])).total_seconds()
    if age > 90: 
        st.warning(f'Engine heartbeat stale: {age:.0f} seconds. Values below are historical.')
        
    st.write('Engine:', data['health'], ' • Updated:', data['heartbeat'])
    if data.get('account'): 
        st.json(data['account'], expanded=False)
        
    snapshots = data.get('snapshots', {})
    rows = []
    for ticker, s in snapshots.items():
        rows.append({
            'Ticker': ticker, 
            'State': s.get('stage'), 
            'Reason': s.get('reason_code'),
            'Bar': s.get('features', {}).get('latest_5m_ts'),
            'VIC': (s.get('vic') or {}).get('verdict')
        })
        
    st.dataframe(rows, width='stretch', hide_index=True)
    if not snapshots: 
        return
        
    ticker = st.selectbox('Ticker', list(snapshots))
    s = snapshots[ticker]
    f = s.get('features', {})
    orb = f.get('orb', {})
    c = s.get('candidate', {})
    
    st.write('State:', s.get('stage'), ' • Reason:', s.get('reason_code'))
    
    levels = {
        k: orb.get(k) for k in ['orb30_high', 'orb30_low', 'orb30_mid', 'accepted_or_high', 'accepted_or_low']
    }
    levels.update(
        current_completed_close=f.get('close'), 
        vwap=f.get('vwap'),
        orb_width_percentile=f.get('orb_width_context', {}).get('percentile'), 
        extension_r=c.get('extension_r')
    )
    st.dataframe([levels], hide_index=True, width='stretch')
    
    chart = f.get('chart', [])
    if chart:
        df = pd.DataFrame(chart)
        fig = go.Figure(go.Candlestick(
            x=df.timestamp, open=df.Open, high=df.High, low=df.Low, close=df.Close, name='Completed 5m'
        ))
        fig.add_trace(go.Scatter(x=df.timestamp, y=df.VWAP, name='VWAP'))
        
        for label, k in [
            ('ORB High', 'orb30_high'), ('ORB Low', 'orb30_low'), 
            ('ORB midpoint', 'orb30_mid'), ('Accepted OR High', 'accepted_or_high'), 
            ('Accepted OR Low', 'accepted_or_low')
        ]:
            if orb.get(k) is not None: 
                fig.add_hline(y=orb[k], line_dash='dash', annotation_text=label)
                
        for marker in s.get('machine', {}).get('markers', []):
            fig.add_trace(go.Scatter(x=[marker['timestamp']], y=[marker['price']], mode='markers', name=marker['kind']))
            
        if c:
            fig.add_hline(y=c['stop'], annotation_text='Frozen stop', line_color='red')
            for name, value in c.get('targets', {}).items():
                if value is not None: 
                    fig.add_hline(y=value, line_dash='dot', annotation_text=name)
            fig.add_trace(go.Scatter(x=[c['decision_ts']], y=[c['entry_spot']], mode='markers', name='Entry reference (underlying)'))
            
        obstacle = (s.get('vic') or {}).get('nearest_obstacle')
        if obstacle is not None: 
            fig.add_hline(y=obstacle, annotation_text='VIC obstacle', line_color='orange')
            
        fig.update_layout(template='plotly_dark', height=600, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, width='stretch')
        
    st.caption('Underlying entry reference is not an actual underlying fill. Actual option fills are shown below.')
    
    for label, value in [
        ('Breach state', s.get('machine')), ('RVOL', f.get('rvol')), 
        ('Alpha — shadow', s.get('alpha')), ('VIC', s.get('vic')), 
        ('Contract', s.get('option')), ('Candidate', c)
    ]:
        with st.expander(label): 
            st.json(value or {})
            
    orders = [o for o in data.get('orders', {}).values() if o['ticker'] == ticker]
    st.subheader('Broker-reconciled orders and actual option fills')
    for o in orders: 
        st.json(o, expanded=False)
        
    with st.expander('Active configuration'): 
        st.json(data['config'])

if __name__ == '__main__': 
    main()