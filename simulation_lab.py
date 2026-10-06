"""Read-only saved-run view. Independent of the six paper team order paths."""
import json,os
from pathlib import Path

def render():
    import streamlit as st
    root=Path(os.environ.get('SIMULATION_REPORTS_DIR',str(Path(__file__).resolve().parent.parent/'simulation'/'reports'))).expanduser()
    st.subheader('Simulation laboratory')
    st.caption('Saved historical experiments only. These cards never start trading teams or place orders.')
    candidates=sorted([p for p in root.glob('*/summary.json') if p.is_file()],key=lambda p:p.stat().st_mtime,reverse=True) if root.is_dir() else []
    if not candidates:
        st.info('No saved simulation runs available on this computer. Run the simulator, then refresh. The hosted dashboard needs a separately supplied report to show these local experiments.')
        return
    selected=st.selectbox('Saved run',[p.parent.name for p in candidates],key='simulation_run')
    path=next(p for p in candidates if p.parent.name==selected)
    try:report=json.loads(path.read_text())
    except (OSError,ValueError):st.error('The selected report could not be read.');return
    st.info(report.get('simulation_label','Pricing provenance unavailable'))
    c=report.get('config',{});st.caption(f"{c.get('start')} to {c.get('end')} · daily starting cash ${c.get('budget',0):,.0f} · {len(report.get('teams',{}))} simulated teams")
    items=list(report.get('teams',{}).items())
    for index in range(0,len(items),2):
        columns=st.columns(2)
        for col,(tid,t) in zip(columns,items[index:index+2]):
            with col:
                st.markdown('#### '+tid.replace('team','Team '))
                st.write(t.get('label',tid));net=t.get('net_pnl_closed',0)
                st.metric('Cumulative net P&L',f'${net:+,.2f}',delta=f'${net:+,.2f}')
                rate=t.get('win_rate');st.caption(f"Closed: {t.get('closed_trades',0)} · wins: {t.get('wins',0)} · losses: {t.get('losses',0)} · win rate: {100*rate:.1f}%" if rate is not None else 'No closed trades')
                st.caption(f"Profitable days: {t.get('profitable_days','—')} · losing days: {t.get('losing_days','—')} · no-trade days: {t.get('no_trade_days','—')}")
                with st.expander('Entry / exit rules and diagnostics'):
                    st.write('Entry: '+t.get('entry_rules','Unavailable'));st.write('Exit: '+t.get('exit_rules','Unavailable'))
                    st.write(dict(expectancy=t.get('expectancy_net_per_trade'),profit_factor=t.get('profit_factor'),drawdown=t.get('max_sampled_mark_drawdown')))
                    st.dataframe([dict(reason=k,count=v) for k,v in sorted(t.get('skips',{}).items(),key=lambda x:-x[1])[:10]],hide_index=True)
    st.caption('Net P&L adds daily results; it is not a compounded account balance. Model win rates are not validated historical option returns.')
    chart=path.parent/'comparison.html'
    if chart.exists():
        with st.expander('Interactive QQQ trade charts'):
            import streamlit.components.v1 as components
            components.html(chart.read_text(),height=1100,scrolling=True)
    pdf=path.parent/'comparison.pdf'
    if pdf.exists():st.download_button('Download simulation summary PDF',pdf.read_bytes(),file_name=selected+'_summary.pdf',mime='application/pdf')
