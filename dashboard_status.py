"""Display-only research status and bounded public daily-yield retrieval."""
import io
import ssl
from datetime import timedelta
from urllib.request import Request, urlopen
import certifi
import pandas as pd
from dashboard_data import daily_observation


def fetch_treasury(now, opener=urlopen):
    result={}
    context=ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    for series in ('DGS10','DGS2'):
        try:
            url='https://fred.stlouisfed.org/graph/fredgraph.csv?id='+series+'&cosd='+str((now-timedelta(days=30)).date())
            with opener(Request(url,headers={'User-Agent':'VictorTerminal/2'}),timeout=10,
                        context=context) as response:
                payload=response.read(2_000_001)
            if len(payload)>2_000_000:raise ValueError('Response exceeds size limit')
            frame=pd.read_csv(io.BytesIO(payload),index_col=0,parse_dates=True)
            row=daily_observation(frame[[series]],now)
            if not row:raise ValueError('No numeric observations')
            # Never silently substitute a years-old observation after partial reads.
            if (now.date()-pd.Timestamp(row['date']).date()).days>7:
                result[series]={'error':'Observation older than seven days','date':row['date']}
            else:result[series]=row
        except Exception as exc:
            result[series]={'error':type(exc).__name__}
    return result


def select_research(data):
    brief=data.get('brief') or {};monitor=data.get('monitor') or {}
    if monitor and brief.get('session_date')!=monitor.get('session_date'):return monitor
    return brief or monitor


def research_status(brief,now):
    if brief.get('slot')=='MONITOR':return 'Collecting preview · not an entry briefing'
    if brief.get('session_date')!=str(now.date()):return 'Different session · unavailable for entry'
    if brief.get('status')!='READY':return 'Briefing '+str(brief.get('status') or 'unavailable')+' · unavailable for entry'
    try:
        issued=pd.Timestamp(brief.get('issued_at'));end=pd.Timestamp(brief.get('valid_until'))
        if pd.isna(issued) or pd.isna(end):raise ValueError()
        if now<issued:return 'Not yet valid · unavailable for entry'
        if now>=end:return 'Expired · unavailable for entry'
        if brief.get('slot') not in ('0915','0925'):return 'Unknown briefing slot · unavailable for entry'
        return 'Active morning context'
    except (TypeError,ValueError):return 'Validity timestamps unavailable · unavailable for entry'


def ai_schedule_lines(data,brief,now):
    opening=brief.get('session_open')
    lines=['AI request windows: 09:12–09:14 and 09:22–09:24 ET on trading days; briefing publication: 09:15 and 09:25 ET.']
    try:
        start=pd.Timestamp(opening)
        if pd.isna(start):raise ValueError()
        windows=[(start-timedelta(minutes=m),start-timedelta(minutes=m-2)) for m in (18,8)]
        upcoming=next(((a,b) for a,b in windows if now<b),None)
        if upcoming:
            a,b=upcoming
            lines.append(('Current' if now>=a else 'Next')+' request window: '+a.tz_convert('America/New_York').strftime('%b %d, %Y %I:%M %p %Z')+' (requires worker and collected inputs).')
        else:lines.append('This session’s AI request windows have ended.')
    except (TypeError,ValueError):lines.append('Next session time unavailable in telemetry.')
    completed=data.get('ai_last_success_at')
    lines.append('Last successful AI synthesis this session: '+(str(completed) if completed else 'not recorded in available telemetry.'))
    if (brief.get('ai') or {}).get('status')=='NOT_REQUESTED':lines.append('No AI synthesis attached to this preview; this is not an authentication result.')
    return lines
