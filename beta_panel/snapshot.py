"""Read only the Beta ledger. Never import its runner, broker or provider clients."""
from datetime import datetime, timezone
import json
import math
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

MAX_BYTES = 8_000_000
CONFIG = dict(max_positions=10, max_premium=2000, max_total_premium=20000,
              dte_min=85, dte_target=90, dte_max=95, option_feed='opra', intraday_reserve=30000)
SECTIONS = ('positions', 'orders', 'events', 'dossiers', 'validations', 'entry_checks')
OBJECTS = ('status', 'scan', 'compatibility', 'sec_health')
RUNTIME_FIELDS = {'heartbeat_at', 'last_progress_at', 'stage_started_at', 'started_at', 'status',
                  'stage', 'current_symbol', 'thread_alive', 'error_type', 'next_action_at',
                  'attempted_count', 'universe_count', 'covered_count', 'finalist_index', 'finalist_total'}
INTERNAL_SCAN_FIELDS = {'symbols', 'packets', 'candidates', 'finalist_packets', 'finalist_results', 'covered_symbols'}
PRIVATE_KEY = re.compile(r'(secret|token|password|credential|authorization|api.?key|user.agent|account|buying.power|cash.balance|equity.balance|headers|environment|^env$)', re.I)
THESIS_FIELDS = set('''id symbol company direction summary bull_case bear_case catalyst catalyst_date
invalidation entry_rationale hold_rationale valuation_basis priced_in_analysis business_quality
balance_sheet_analysis earnings_quality uncertainty target_price bear_price base_price bull_price
thesis_status position_action action_rationale move_horizon_days move_rationale move_assumptions
move_evidence_ids rank_score supporting_evidence_ids opposing_evidence_ids valuation_evidence_ids
catalyst_evidence_ids missing_information as_of valid_until research_status research_scorecard
base_case_directional_move evidence fundamentals spot_price spot_price_as_of validation_status
proposed_contract option events research_version policy_version scoring_version scorecard
failure_stage failure_phase failure_type failure_http_status failure_provider_code failure_provider_type
failure_response_status failure_incomplete_reason'''.split())


class SnapshotError(ValueError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat()


def clean(value, secrets=(), depth=0):
    """Strip credential fields and known credential values, including nested text.

    Only explicitly selected ledger collections reach this function. Never pass
    a configuration object, environment, identity document or broker account.
    """
    if depth > 24:
        raise SnapshotError('Research record nesting exceeds supported depth')
    if isinstance(value, dict):
        return {k: clean(v, secrets, depth + 1) for k, v in value.items()
                if isinstance(k, str) and not PRIVATE_KEY.search(k)}
    if isinstance(value, list):
        return [clean(v, secrets, depth + 1) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret and len(secret) >= 8:
                value = value.replace(secret, '[redacted]')
        # Source URLs need neither embedded credentials nor query tokens.
        if value.startswith(('https://', 'http://')):
            try:
                url = urlsplit(value)
                value = urlunsplit((url.scheme, url.hostname or '', url.path, '', ''))
            except ValueError:
                return '[invalid URL]'
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise SnapshotError('Unsupported value in research record')


def validate(raw, secrets=(), *, enforce_limit=True):
    if not isinstance(raw, dict) or raw.get('schema') != 1 or raw.get('paper') is not True:
        raise SnapshotError('Invalid Beta paper snapshot')
    try:
        when = datetime.fromisoformat(raw['observed_at'].replace('Z', '+00:00'))
        if when.tzinfo is None:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SnapshotError('Missing snapshot timestamp') from None
    out = dict(schema=1, paper=True, observed_at=when.isoformat())
    for key in SECTIONS:
        rows = raw.get(key)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise SnapshotError('Invalid Beta record collection')
        out[key] = clean(rows, secrets)
    for key in OBJECTS:
        if not isinstance(raw.get(key), dict):
            raise SnapshotError('Invalid Beta status record')
        out[key] = clean(raw[key], secrets)
    out['scan'] = {k: v for k, v in out['scan'].items() if k not in INTERNAL_SCAN_FIELDS}
    runtime = raw.get('runtime') or {}
    if not isinstance(runtime, dict):
        raise SnapshotError('Invalid runtime status')
    out['runtime'] = {key: clean({k: v for k, v in row.items() if k in RUNTIME_FIELDS}, secrets)
                      for key, row in runtime.items() if key in ('engine', 'research') and isinstance(row, dict)}
    for key in ('actual_state', 'research_inflight'):
        if key in runtime:
            out['runtime'][key] = clean(runtime[key], secrets)
    config = raw.get('config')
    if not isinstance(config, dict):
        raise SnapshotError('Invalid display configuration')
    out['config'] = {key: clean(config.get(key, default), secrets) for key, default in CONFIG.items()}
    if out['config']['max_positions'] != 10:
        raise SnapshotError('Unsupported position display limit')
    out['dossiers'] = [{k: v for k, v in row.items() if k in THESIS_FIELDS} for row in out['dossiers']]
    encoded = json.dumps(out, ensure_ascii=False, allow_nan=False).encode()
    if enforce_limit and len(encoded) > MAX_BYTES:
        raise SnapshotError('Snapshot exceeds 8 MB; no partial portfolio was published. Use the local dashboard.')
    return out


def read_local(project_dir, *, data_dir=None, secrets=()):
    project = Path(project_dir).expanduser().resolve()
    from dotenv import dotenv_values
    # Parse without interpolation or exporting the project's API keys to the host.
    env = dotenv_values(project / '.env', interpolate=False)
    private_values = tuple(v for k, v in env.items() if PRIVATE_KEY.search(k) and v)
    data = Path(data_dir or env.get('BETA_DATA_DIR') or project / 'data').expanduser()
    if not data.is_absolute():
        data = project / data
    ledger = data / 'beta.sqlite3'
    if not ledger.is_file():
        raise SnapshotError('Beta ledger not found. Set BETA_RESEARCH_DIR to the existing Beta Research folder.')
    # mode=ro fails rather than creating a new empty database. Do not use immutable
    # mode: the runner writes WAL records that must be visible to this reader.
    db = sqlite3.connect(ledger.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        def rows(sql, params=()):
            return [json.loads(r[0]) for r in db.execute(sql, params)]
        def documents(kind):
            return rows('SELECT payload FROM documents WHERE kind=? ORDER BY key', (kind,))
        def latest(kind):
            result = rows('SELECT payload FROM documents WHERE kind=? AND key=?', (kind, 'latest'))
            return result[0] if result else {}
        out = dict(schema=1, paper=True, observed_at=stamp(), config=dict(CONFIG),
                   positions=rows('SELECT payload FROM positions ORDER BY rowid DESC'),
                   orders=rows('SELECT payload FROM orders ORDER BY rowid DESC'),
                   dossiers=documents('thesis'), validations=documents('validation'),
                   entry_checks=documents('entry_check'),
                   status=latest('status'), scan=latest('scan'),
                   compatibility=latest('compatibility'), sec_health={}, runtime={})
        for worker in ('engine', 'research'):
            found = rows('SELECT payload FROM documents WHERE kind=? AND key=?', ('runtime', worker))
            if found:
                out['runtime'][worker] = found[0]
        out['events'] = [dict(json.loads(r[2]), id=r[0], at=r[1]) for r in
                         db.execute('SELECT id,at,payload FROM events ORDER BY id DESC LIMIT 200')]
    finally:
        db.close()
    out['config']['option_feed'] = env.get('BETA_OPTION_FEED') or 'opra'
    out['config']['intraday_reserve'] = env.get('BETA_INTRADAY_RESERVE') or 30000
    try:
        runtime = json.loads((data / 'unified_runtime.json').read_text())
        if isinstance(runtime, dict) and runtime.get('version') == 'beta-runtime-v1':
            for key in ('engine', 'research', 'actual_state', 'research_inflight'):
                if key in runtime:
                    out['runtime'][key] = runtime[key]
    except (OSError, ValueError, TypeError):
        pass  # Older engine versions have no live worker record.
    try:
        path = data / 'sec_cache' / 'access_state.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        out['sec_health'] = {k: state[k] for k in (
            'requests', 'status', 'last_endpoint', 'last_http_status', 'error_kind',
            'last_request', 'last_success', 'last_success_endpoint', 'pause_until') if k in state}
        out['sec_health']['paused'] = time.time() < float(state.get('pause_until', 0))
    except (OSError, ValueError, TypeError):
        out['sec_health'] = dict(paused=True, status='unreadable_access_state')
    # Avoid exporting internal scan queues and the entire discovered symbol list.
    out['scan'] = {k: v for k, v in out['scan'].items() if k not in INTERNAL_SCAN_FIELDS}
    out['compatibility'] = {k: v for k, v in out['compatibility'].items() if k in ('reason', 'verified', 'status')}
    return validate(out, secrets=(*secrets, *private_values), enforce_limit=False)
