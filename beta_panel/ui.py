"""Embedded Beta Research evidence and operational diagnostics; no runner imports."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from .views import (
    ACTIVE_STATES,
    age_minutes,
    cell,
    label,
    money,
    number,
    position_rows,
    persistent_tabs,
    premium,
    rank_dossiers,
    research_progress,
    safe_url,
    timestamp,
)


def text_block(title: str, value: Any) -> None:
    st.markdown(f"**{title}**")
    if value is None or value == "" or value == []:
        st.caption("Not documented. No conclusion is assumed.")
    elif isinstance(value, list):
        for item in value:
            st.write(item)
    elif isinstance(value, dict):
        st.json(value, expanded=False)
    else:
        st.write(str(value))


def render_evidence(evidence: Any) -> None:
    if not isinstance(evidence, list) or not evidence:
        st.info("No source evidence has been recorded for this thesis.")
        return
    for index, source in enumerate(evidence, 1):
        if not isinstance(source, dict):
            st.write(source)
            continue
        title = source.get("title") or source.get("id") or f"Source {index}"
        with st.expander(str(title), expanded=index <= 2):
            st.caption(f"Published: {timestamp(source.get('published_at'))}")
            url = safe_url(source.get("url"))
            if url:
                st.link_button("Open original source ↗", url)
            else:
                st.caption("No usable original-source URL recorded.")
            st.write(source.get("excerpt") or source.get("summary") or "No excerpt recorded.")
            if source.get("retrieved_at"):
                st.caption(f"Retrieved: {timestamp(source['retrieved_at'])}")


def render_fundamentals(data: Any) -> None:
    if not isinstance(data, dict) or not data:
        st.info("Financial-statement and valuation data have not been collected for this company.")
        return
    st.caption("Figures are shown as recorded by the research pipeline. Missing values are not treated as zero; units and reporting periods must be checked before interpretation.")
    scalar = [{"Metric": label(key), "Recorded value": cell(value)} for key, value in data.items() if not isinstance(value, (dict, list))]
    if scalar:
        st.dataframe(scalar, hide_index=True, width="stretch")
    metrics = data.get("metrics")
    if isinstance(metrics, dict):
        st.markdown("**Financial statement metrics**")
        rows = []
        for name, metric in metrics.items():
            metric = metric if isinstance(metric, dict) else {"value": metric}
            rows.append({"Metric": label(name), "Value": cell(metric.get("value")), "Unit": cell(metric.get("unit")),
                         "Period start": cell(metric.get("period_start")), "Period end": cell(metric.get("period_end")),
                         "Filed": cell(metric.get("filed_at")), "Method": cell(metric.get("method")), "Sources": cell(metric.get("source_ids"))})
        st.dataframe(rows, hide_index=True, width="stretch")
    quarters = data.get("quarterly")
    if isinstance(quarters, dict):
        with st.expander("Quarterly financial history"):
            for name, records in quarters.items():
                st.markdown(f"**{label(name)}**")
                if isinstance(records, list) and records:
                    st.dataframe([{label(k): cell(v) for k, v in record.items()} for record in records if isinstance(record, dict)], hide_index=True, width="stretch")
                else:
                    st.caption("No usable quarterly history recorded.")
    for key, value in data.items():
        if key in {"metrics", "quarterly"}:
            continue
        if isinstance(value, dict):
            with st.expander(label(key), expanded=key in {"balance_sheet", "valuation", "cash_flow", "income_statement"}):
                st.dataframe([{"Metric": label(k), "Recorded value": cell(v)} for k, v in value.items()], hide_index=True, width="stretch")
        elif isinstance(value, list):
            with st.expander(label(key)):
                st.json(value, expanded=False)


def render_scorecard(card: dict[str, Any], research: dict[str, Any]) -> None:
    if not card:
        st.info('No current rubric score recorded. A fresh research review is required.')
        return
    total = number(card.get('total'))
    if total is None:
        points = number(card.get('research_points'))
        st.metric('Research evidence points', f'{points:g} / 90' if points is not None else 'Unavailable')
        st.info('Final score pending contract checks: up to 10 additional points. No entry is approved from the research subtotal.')
    else:
        st.metric('Entry evidence score', f'{total:g} / 100')
        st.caption(f"Score band: {label(card.get('band'))} · Scored at {timestamp(card.get('scored_at'))}")
    st.caption('Minimum 90/100 AND all mandatory checks. Points are not win probabilities. This rubric has not demonstrated profitability.')
    st.dataframe([{'Component':label(c.get('name')), 'Points':c.get('points'), 'Maximum':c.get('maximum'),
                   'Why':c.get('rationale'), 'Deductions':cell(c.get('deductions')),
                   'What would change it':c.get('improvement_needed'), 'Source IDs':cell(c.get('evidence_ids'))}
                  for c in card.get('components',[])], hide_index=True, width='stretch')
    for c in card.get('components',[]):
        if c.get('criteria'):
            with st.expander(label(c['name']) + ' calculations'):
                st.dataframe(c['criteria'],hide_index=True,width='stretch')
    for reason in card.get('errors',[]) + card.get('critical_concerns',[]):
        st.warning(reason)
    st.markdown('**Company-specific news and events**')
    for event in research.get('events',[]):
        with st.expander(f"{event.get('title')} · {event.get('points',0):g}/30 · {label(event.get('effect'))}"):
            st.caption(f"Event date: {cell(event.get('event_date'))} · Supports chosen direction: {cell(event.get('supports_direction'))}")
            text_block('Financial effect',event.get('financial_effect'))
            text_block('Why now?',event.get('timing_explanation'))
            text_block('Already priced in?',event.get('priced_in_analysis'))
            st.dataframe([{'Criterion':label(c['name'].rsplit('.',1)[-1]), 'Rating / 5':c.get('rating'),
                           'Why':c.get('rationale'), 'Deductions':cell(c.get('deductions')),
                           'Source IDs':cell(c.get('evidence_ids'))} for c in event.get('criteria',[])],
                         hide_index=True,width='stretch')
    if not research.get('events'):
        st.caption('No scored company event is recorded.')
    st.caption('The strongest supporting event counts once. Its weakest causal criterion sets its score. Opposing events remain visible; critical contradictions block entry.')


def render_dossier(thesis: dict[str, Any], positions: list[dict[str, Any]], events: list[dict[str, Any]], entry_check=None) -> None:
    st.subheader(f"{thesis.get('symbol', 'Unknown')} · {thesis.get('company') or 'Company research'}")
    cols = st.columns(4)
    cols[0].metric("Research direction", label(thesis.get("direction")))
    cols[1].metric("Thesis", label(thesis.get("thesis_status")))
    research = thesis.get('research_scorecard') or {}
    cols[2].metric("Research points / 90", cell(research.get('research_points')))
    cols[3].metric("Evidence status", label(thesis.get("research_status")))
    st.caption(f"Research as of {timestamp(thesis.get('as_of'))} · Valid until {timestamp(thesis.get('valid_until'))} · Evidence points are not a probability of profit.")
    st.write(thesis.get("summary") or "The investment thesis has not been documented.")
    check = entry_check if entry_check and entry_check.get('thesis_id') == thesis.get('id') else {}
    if check.get('reason'):
        st.info('Latest entry check: ' + check['reason'])
    views = persistent_tabs(["Decision & contract", "Company financials", "Sources & opposing case", "Review history", "Score & company events"], key='vt_beta_dossier_tab')
    with views[4]:
        render_scorecard(check.get('scorecard') or research, research)
    with views[0]:
        left, right = st.columns(2)
        with left:
            text_block("Why enter?", thesis.get("entry_rationale"))
            text_block("Why continue holding?", thesis.get("hold_rationale"))
            text_block("Recommended position action", thesis.get("position_action"))
            text_block("Reason for this action", thesis.get("action_rationale"))
            text_block("What would invalidate the thesis?", thesis.get("invalidation"))
        with right:
            text_block("Expected catalyst", thesis.get("catalyst"))
            st.caption(f"Catalyst date: {cell(thesis.get('catalyst_date'))}")
            st.dataframe(
                [{"Stock-price scenario": title, "Recorded price": money(thesis.get(key))} for title, key in [("Bear", "bear_price"), ("Base", "base_price"), ("Bull", "bull_price"), ("Target", "target_price")]],
                hide_index=True, width="stretch",
            )
            st.caption("These are stock-price scenarios, not option-return predictions.")
            move = number(thesis.get('base_case_directional_move'))
            st.metric('Projected stock move in the chosen direction', f'{move:.1%}' if move is not None else 'Unavailable')
            st.caption(f"New-entry minimum: 20% in the base case · Research horizon: {cell(thesis.get('move_horizon_days'))} days. This is an uncalibrated estimate, not a probability or guaranteed return.")
            text_block('Evidence for the size and timing of the move', thesis.get('move_rationale'))
            text_block('Target assumptions', thesis.get('move_assumptions'))
            text_block('Move evidence IDs', thesis.get('move_evidence_ids'))
        related = [p for p in positions if (p.get("thesis_id") and p.get("thesis_id") == thesis.get("id")) or p.get("symbol") == thesis.get("symbol")]
        st.markdown("**Recorded contracts**")
        if related:
            st.dataframe(position_rows(related), hide_index=True, width="stretch")
        else:
            st.info("No position or selected contract is recorded. A researched company is not automatically an approved trade.")
        proposed = thesis.get("proposed_contract") or thesis.get("option")
        if proposed:
            st.json(proposed, expanded=False)
        st.caption(f"Validation status: {label(thesis.get('validation_status') or 'UNVALIDATED_PAPER')}. Historical performance must be documented separately from the research narrative.")
    with views[1]:
        text_block("Business quality", thesis.get("business_quality"))
        left, right = st.columns(2)
        with left:
            text_block("Balance-sheet assessment", thesis.get("balance_sheet_analysis"))
            text_block("Earnings quality", thesis.get("earnings_quality"))
        with right:
            text_block("Valuation basis", thesis.get("valuation_basis"))
            text_block("What is already priced in?", thesis.get("priced_in_analysis"))
        st.caption(f"Recorded stock price: {money(thesis.get('spot_price'))} · As of {timestamp(thesis.get('spot_price_as_of'))}")
        render_fundamentals(thesis.get("fundamentals"))
    with views[2]:
        left, right = st.columns(2)
        with left:
            text_block("Bullish case", thesis.get("bull_case"))
        with right:
            text_block("Bearish case", thesis.get("bear_case"))
        text_block("Uncertainty", thesis.get("uncertainty"))
        text_block("Missing information", thesis.get("missing_information"))
        failure = {key: thesis[key] for key in (
            'failure_stage', 'failure_phase', 'failure_type', 'failure_http_status',
            'failure_provider_code', 'failure_provider_type',
            'failure_response_status', 'failure_incomplete_reason') if thesis.get(key) is not None}
        if failure:
            st.write('Research failure details', failure)
        st.markdown("**Source evidence**")
        render_evidence(thesis.get("evidence"))
    with views[3]:
        matched = [e for e in events if (thesis.get("symbol") and e.get("symbol") == thesis.get("symbol")) or (thesis.get("id") and e.get("thesis_id") == thesis.get("id"))]
        if not matched:
            st.info("No review events have been recorded for this company.")
        render_events(matched[:50])


def render_events(events: list[dict[str, Any]]) -> None:
    for event in events:
        when = event.get("created_at") or event.get("timestamp") or event.get("at")
        title = event.get("event_type") or event.get("type") or event.get("kind") or "Event"
        summary = event.get("message") or event.get("reason") or event.get("summary")
        with st.expander(f"{timestamp(when)} · {label(title)} · {event.get('symbol', '')}"):
            if summary:
                st.write(summary)
            st.json(event, expanded=False)


def render_slot(index: int, position: dict[str, Any] | None) -> None:
    esc = lambda value: html.escape(str(value))
    if position is None:
        st.markdown(f'<div class="slot empty"><div class="index">Slot {index:02d}</div><div class="stock">Available</div><div class="detail">Waiting for qualified research and a tradable contract.</div><div class="neutral">No position</div></div>', unsafe_allow_html=True)
        return
    pnl = number(position.get("unrealized_pnl"))
    color = "gain" if pnl is not None and pnl >= 0 else "loss" if pnl is not None else "neutral"
    pnl_text = money(pnl, signed=True) if pnl is not None else "P/L unavailable"
    st.markdown(
        f'<div class="slot"><div class="index">Slot {index:02d} · {esc(label(position.get("state")))}</div>'
        f'<div class="stock">{esc(position.get("symbol", "Unknown"))} <span style="font-size:.75rem;color:#aabbd2">{esc(label(position.get("direction")))}</span></div>'
        f'<div class="detail">Strike {esc(money(position.get("strike")))}<br>Expires {esc(position.get("expiration") or "Not recorded")}<br>Entry {esc(money(premium(position)))}</div>'
        f'<div class="{color}">{esc(pnl_text)}</div></div>', unsafe_allow_html=True,
    )


def render_runtime(runtime: dict, scan: dict) -> None:
    """Keep worker liveness separate from progress on a potentially slow request."""
    st.markdown('#### Live activity')
    if not runtime or not any(runtime.get(key) for key in ('engine', 'research')):
        st.info('Live worker details have not arrived. Saved scan totals alone do not confirm an active scan.')
        return
    for col, key, title in zip(st.columns(2), ('engine', 'research'), ('Position monitor', 'Company researcher')):
        with col:
            worker = runtime.get(key) or {}
            heartbeat_age = age_minutes(worker.get('heartbeat_at'))
            live = heartbeat_age is not None and -0.1 <= heartbeat_age <= 1.5 and worker.get('thread_alive') is True
            state = label(worker.get('status')) if live else 'No fresh worker heartbeat'
            st.markdown('**'+title+' · '+state+'**')
            st.caption('Heartbeat '+timestamp(worker.get('heartbeat_at')))
            st.caption('Last progress '+timestamp(worker.get('last_progress_at')))
            stage = worker.get('stage')
            if stage:
                st.caption(label(stage)+((' · '+str(worker['current_symbol'])) if worker.get('current_symbol') else ''))
            if worker.get('next_action_at'):
                st.caption('Next scheduled work '+timestamp(worker['next_action_at']))
            if worker.get('error_type'):
                st.warning('Worker diagnostic: '+str(worker['error_type']))
            progress_age = age_minutes(worker.get('last_progress_at'))
            if live and worker.get('status') == 'working' and progress_age is not None and progress_age > 5:
                st.warning('Worker is alive, but no progress checkpoint has arrived for over five minutes.')
    if runtime.get('research_inflight'):
        st.caption('An existing research request is finishing. OFF prevents the next research cycle.')
    if runtime.get('actual_state'):
        st.caption('Engine state: '+label(runtime['actual_state']))


def render(snapshot: dict) -> None:
    from types import SimpleNamespace
    config = SimpleNamespace(**snapshot['config'])
    positions, orders, events = (snapshot[k] for k in ('positions', 'orders', 'events'))
    status, scan, compatibility, sec_health = (snapshot[k] for k in ('status', 'scan', 'compatibility', 'sec_health'))
    dossiers = rank_dossiers(snapshot['dossiers'])
    progress = research_progress(scan, dossiers)
    if progress:
        message = (f"Screening complete · AI research completed: {progress['completed']}/{progress['total']}"
                   f" · Unresolved: {progress['pending']}")
        if progress['pending']:
            st.warning(message)
            st.caption(' · '.join(f'{name}: {count}' for name, count in progress['counts'].items() if count))
        else:
            st.info(message)
        if progress['completed'] == 0:
            st.caption('No finalist completed AI research in this round. Research errors do not qualify a company for entry.')
    validations = snapshot['validations']
    entry_checks = {row.get('thesis_id'): row for row in snapshot['entry_checks']}
    st.markdown("""<style>
    .slot {padding:15px;border:1px solid #2b3c52;border-radius:10px;min-height:178px;margin-bottom:12px;overflow-wrap:anywhere}
    .slot.empty {border-style:dashed}.slot .index{font-size:.7rem}.slot .stock{font-size:1.25rem;font-weight:700;margin:9px 0 5px}
    .slot .detail{font-size:.8rem}.slot .gain{color:#28ac8c}.slot .loss{color:#dd6868}
    </style>""", unsafe_allow_html=True)
    active = [p for p in positions if str(p.get("state", "")).lower() in ACTIVE_STATES]
    closed = [p for p in positions if p.get("state") == "closed"]
    max_positions = int(getattr(config, "max_positions", 10))
    st.markdown('<div class="eyebrow">COMPANY RESEARCH / 90-DAY OPTIONS</div>', unsafe_allow_html=True)
    st.subheader("Beta Research · Evidence before exposure.")
    st.markdown('<div class="intro">A separate paper portfolio, with every decision connected to its thesis and source evidence.</div>', unsafe_allow_html=True)
    connection = status.get("connection")
    automation = status.get("automation")
    st.caption(f"Connection: {cell(connection) if connection is not None else 'Not reported'} · Automation: {cell(automation) if automation is not None else 'Not reported'} · Last runner update: {timestamp(status.get('last_tick'))}")
    st.caption(f"New entries enabled: {cell(status.get('entries_enabled'))} · Market open: {cell(status.get('market_open'))}")
    coexistence = status.get("coexistence_verified", status.get("coexistence"))
    feed = str(getattr(config, "option_feed", "Not configured"))
    st.caption(f"Options feed: {feed.upper()} · Shared-account coexistence: {cell(coexistence) if coexistence is not None else 'Not verified'}")
    if compatibility.get("reason"):
        with st.expander("Shared-account coexistence details"):
            st.write(compatibility["reason"])
    if feed == "indicative":
        st.warning("Indicative options data: exploratory paper results only. Quotes and P/L do not establish executable OPRA pricing or realistic strategy performance.")
    if not status:
        st.info("Waiting for the first runner update. No broker connection or active automation has been confirmed.")
    elif status.get("error"):
        st.error("The runner reports an error. Inspect Activity and local runner logs before relying on the displayed state.")
    age = age_minutes(status.get("last_tick"))
    if age is not None and age > 5:
        st.warning(f"Runner state is {int(age)} minutes old. Quotes and position status may be stale.")
    if len(active) > max_positions:
        st.error("Active ledger holdings exceed the configured limit. New entries must remain blocked until reconciled.")
    if any(p.get("state") == "quarantine" for p in active):
        st.warning("At least one position is quarantined pending reconciliation. Its slot remains occupied.")
    render_runtime(snapshot.get('runtime') or {}, scan)

    tabs = persistent_tabs(["Overview", "Research", "Positions", "Activity"], key='vt_beta_tab')
    with tabs[0]:
        with st.expander("Portfolio mandate"):
            st.write("Paper only · 10 stocks maximum · One purchased call or put per stock · $2,000 maximum premium per contract · $20,000 total entry premium")
            st.write("Target 90 DTE (85–95) · ATM or up to 5% OTM · Minimum 90/100 evidence score · Minimum projected directional stock move 20% within 30 days")
            st.caption("Evidence scores are not win probabilities. Shared account buying power remains shared with Victor Terminal.")
        cols = st.columns(4)
        cols[0].metric("Active slots", f"{len(active)} / {max_positions}")
        premiums = [premium(p) for p in active]
        cols[1].metric("Recorded entry premium", money(sum(p for p in premiums if p is not None)) if all(p is not None for p in premiums) else "Incomplete")
        open_pnl = [number(p.get("unrealized_pnl")) for p in active]
        cols[2].metric("Unrealized P/L", money(sum(p for p in open_pnl if p is not None), signed=True) if all(p is not None for p in open_pnl) else "Incomplete")
        realized = [number(p.get("realized_pnl")) for p in closed]
        cols[3].metric("Realized P/L", money(sum(p for p in realized if p is not None), signed=True) if all(p is not None for p in realized) else "Incomplete")
        st.caption("P/L reflects recorded project fills and quotes only. Fees are included only where recorded by the execution ledger; unavailable marks are never assumed to be zero.")
        st.subheader("Ten research assignments")
        for start in range(0, max(max_positions, len(active)), 5):
            columns = st.columns(5)
            for offset, col in enumerate(columns):
                index = start + offset
                if index < max(max_positions, len(active)):
                    with col:
                        render_slot(index + 1, active[index] if index < len(active) else None)
        st.caption("Open, opening, closing, reserved, and quarantined records occupy slots until the runner resolves them. A closed position releases its slot for a new company.")
        st.subheader("Research coverage")
        cols = st.columns(4)
        cols[0].metric("Discovered universe", cell(scan.get("universe_count")))
        cols[1].metric("Preliminary screens", cell(scan.get("covered_count")))
        cols[2].metric("Deep research completed", cell(scan.get("research_count", scan.get("researched_count"))))
        fraction = number(scan.get("fully_researched_fraction"))
        cols[3].metric("Universe deeply researched", f"{fraction:.1%}" if fraction is not None else "Not recorded")
        st.caption(f"Scan status: {label(scan.get('status'))} · Updated: {timestamp(scan.get('as_of') or scan.get('updated_at'))} · Started: {timestamp(scan.get('round_started_at'))}")
        st.caption(f"Attempted: {cell(scan.get('attempted_count'))} · Preliminary candidates: {cell(scan.get('eligible_data_count'))} · Full scan attempted: {cell(scan.get('round_complete'))}")
        st.info("Broad screening uses market prices and recent news. Detailed SEC fundamentals are retrieved only for finalists and held-position reviews. Finishing a scan means all discovered companies were attempted, not that every company received full financial research.")
        st.caption("SEC access: at most 1 request/second across processes sharing this project's cache. Saved filing documents are reused. Access denials and rate limits trigger persistent pauses.")
        st.caption(f"SEC requests recorded: {sec_health.get('requests', 0)} · Last recorded result: {sec_health.get('status', 'No requests yet')}")
        if sec_health.get('last_endpoint'):
            st.caption(f"Last SEC endpoint: {sec_health['last_endpoint']} · Detail: {sec_health.get('error_kind') or 'No recorded error'}")
        def sec_time(value):
            from datetime import datetime, timezone
            try:
                return datetime.fromtimestamp(float(value), timezone.utc).isoformat() if value else None
            except (ValueError, TypeError, OverflowError, OSError):
                return None
        if sec_health.get('last_request'):
            st.caption(f"Last attempt: {timestamp(sec_time(sec_health['last_request']))} · Last successful download: {timestamp(sec_time(sec_health.get('last_success')))}")
        if sec_health.get('paused'):
            st.warning("SEC access is paused. New entries wait; monitoring and exits remain enabled. Check the access response and wait for the cooldown—do not bypass it with another process.")
            st.caption(f"Cooldown ends: {timestamp(sec_time(sec_health.get('pause_until')))}")
        if scan.get('finalists_pending'):
            st.caption(f"Finalists still pending: {len(scan['finalists_pending'])} · Next scheduled retry: {timestamp(scan.get('finalist_retry_after'))}")
        if scan.get("scope"):
            text_block("Universe scope", scan["scope"])
        if scan.get("research_selection_note"):
            st.caption(scan["research_selection_note"])
        if scan.get("finalists_analyzed"):
            st.caption("Deep-research finalists: " + ", ".join(str(symbol) for symbol in scan["finalists_analyzed"]))
        if scan.get("errors") or scan.get("failed_symbols") or scan.get("error"):
            with st.expander("Coverage gaps"):
                if scan.get("error"):
                    st.write(scan["error"])
                if scan.get("errors"):
                    st.write(scan["errors"])
                if scan.get("failed_symbols"):
                    st.write({"Failed companies": scan["failed_symbols"]})

    with tabs[1]:
        st.subheader("Ranked company research")
        st.caption("Top ten by research evidence points out of 90. Contract checks add up to 10; entries require a final 90/100 and every mandatory check. Scores are not probabilities.")
        if not dossiers:
            st.info("No company dossiers yet. Run the research pipeline to populate source-backed financial analysis. No sample picks or fabricated trades are shown.")
        else:
            directions = st.multiselect("Direction", ["call", "put", "watch"], default=["call", "put", "watch"], format_func=label, key="beta_direction")
            selected = [t for t in dossiers if t.get("direction", "watch") in directions]
            rows = [{"Rank": index, "Stock": t.get("symbol"), "Company": t.get("company"), "Direction": label(t.get("direction")),
                     "Research / 90": (t.get('research_scorecard') or {}).get('research_points'),
                     "Final / 100": (entry_checks.get(t.get('id'),{}).get('scorecard') or {}).get('total'),
                     "Thesis": label(t.get("thesis_status")), "Research": label(t.get("research_status")), "As of": timestamp(t.get("as_of"))} for index, t in enumerate(selected[:10], 1)]
            if rows:
                st.dataframe(rows, hide_index=True, width="stretch")
            st.caption(f"{len(dossiers)} total dossiers stored · {len(selected)} match this view. Column headers sort the table.")
            if selected:
                index = st.selectbox("Open a complete research dossier", key="beta_dossier", options=range(len(selected)), format_func=lambda i: f"{selected[i].get('symbol', '?')} — {selected[i].get('company') or label(selected[i].get('direction'))}")
                render_dossier(selected[index], positions, events, entry_checks.get(selected[index].get('id')))
            else:
                st.info("No dossiers match the selected directions.")

    with tabs[2]:
        st.subheader("Owned positions")
        if not positions:
            st.info("No project positions are recorded. This does not imply the shared Alpaca account is empty.")
        else:
            filter_state = st.radio("Position view", ["Active", "Closed", "All"], horizontal=True, key="beta_position_view")
            visible = active if filter_state == "Active" else closed if filter_state == "Closed" else positions
            if visible:
                st.dataframe(position_rows(visible), hide_index=True, width="stretch")
                selected_id = st.selectbox("Inspect position decision", key="beta_position", options=range(len(visible)), format_func=lambda i: f"{visible[i].get('symbol', '?')} · {visible[i].get('option_symbol', '')} · {label(visible[i].get('state'))}")
                text_block("Latest recorded reason", visible[selected_id].get("reason"))
                held = visible[selected_id]
                if held.get('entry_scorecard'):
                    with st.expander('Frozen entry score and event evidence'):
                        render_scorecard(held['entry_scorecard'], held['entry_scorecard'])
                with st.expander("Position record"):
                    st.json(visible[selected_id], expanded=False)
            else:
                st.caption("No positions in this view.")
        st.subheader("Order ledger")
        st.caption("An order request is not a fill. Closing orders must fill before a position is treated as closed.")
        if orders:
            order_rows = [{"Created": timestamp(o.get("created_at") or o.get("submitted_at")), "Contract": o.get("option_symbol") or o.get("symbol"), "Side": o.get("side"), "Quantity": o.get("qty"), "Status": o.get("status"), "Limit / share": money(o.get("limit_price")), "Filled quantity": o.get("filled_qty"), "Fill / share": money(o.get("filled_avg_price")), "Client order ID": o.get("client_order_id")} for o in orders]
            st.dataframe(order_rows, hide_index=True, width="stretch")
            with st.expander("Complete order records"):
                st.json(orders[:100], expanded=False)
        else:
            st.caption("No orders recorded.")

    with tabs[3]:
        st.subheader("Decision and execution history")
        st.caption("Latest 200 recorded events. Research updates, skipped entries, holds, exit decisions, and execution failures should remain auditable.")
        if events:
            symbol_filter = st.text_input("Filter by stock symbol", placeholder="All stocks", key="beta_symbol").strip().upper()
            filtered = [e for e in events if not symbol_filter or str(e.get("symbol", "")).upper() == symbol_filter]
            render_events(filtered)
            if not filtered:
                st.caption("No matching events.")
        else:
            st.info("The audit history will appear after the runner records its first event.")

    with tabs[1], st.expander('Validation and evidence of progress'):
        st.subheader("Evidence of progress")
        st.warning("Paper research is unvalidated unless a recorded report establishes otherwise. A convincing narrative, research rank, or correct stock forecast does not prove option profitability.")
        if not validations:
            st.info("No historical validation reports are recorded. Live paper results will accumulate separately; no backtest or win rate is implied.")
        else:
            for index, report in enumerate(validations, 1):
                with st.expander(str(report.get("name") or report.get("id") or f"Validation report {index}"), expanded=index == 1):
                    st.json(report, expanded=False)
        st.markdown("**A usable validation report should document**")
        st.write("Event dates and source availability; companies covered; decision rules fixed before evaluation; historical contract quotes and realistic fills; fees and spreads; unseen evaluation periods; sample size; average gains and losses; drawdown; and data limitations.")
        st.caption("Missing historical options or contemporaneous news must be disclosed. A stock-price simulation must never be labeled an options backtest.")

