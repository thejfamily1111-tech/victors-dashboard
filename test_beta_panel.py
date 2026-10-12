import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from beta_panel.snapshot import read_local, validate, SnapshotError
from beta_panel.transport import rpc, LinkError


class BetaPanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / 'data').mkdir()
        self.db = sqlite3.connect(self.project / 'data' / 'beta.sqlite3')
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''CREATE TABLE documents(kind TEXT,key TEXT,payload TEXT,PRIMARY KEY(kind,key));
            CREATE TABLE positions(id TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE orders(cid TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY,at TEXT,payload TEXT);''')

    def put(self, kind, key, value):
        self.db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?)', (kind, key, json.dumps(value)))
        self.db.commit()

    def test_reads_current_wal_without_changing_ledger_or_environment(self):
        self.put('status', 'latest', {'last_tick': '2026-10-12T00:00:00+00:00'})
        self.db.execute('INSERT INTO positions VALUES(?,?)', ('p', json.dumps({'symbol':'TEST','state':'open','qty':1})))
        self.db.commit()
        before = list(self.db.iterdump())
        result = read_local(self.project)
        self.assertEqual(result['positions'][0]['symbol'], 'TEST')
        self.assertEqual(before, list(self.db.iterdump()))
        self.assertEqual(validate(result), result)

    def test_missing_path_does_not_create_a_project(self):
        missing = self.project / 'missing'
        with self.assertRaises(SnapshotError):
            read_local(missing)
        self.assertFalse(missing.exists())

    def test_private_documents_and_credentials_never_exported(self):
        secret = 'sensitive-example-value-123'
        (self.project / '.env').write_text('OPENAI_API_KEY=' + secret + '\nSEC_USER_AGENT=Owner private@example.com\n')
        self.put('identity', 'account', {'id': 'PRIVATE-ACCOUNT'})
        self.put('thesis', 'TEST', {'id':'t', 'symbol':'TEST', 'summary':'Error: ' + secret,
                 'api_key': secret, 'unknown_private_field':'DO-NOT-EXPORT',
                 'fundamentals': {'metrics': {'cash': {'value':123}}, 'credentials': {'value':secret}},
                 'evidence':[{'url':'https://example.com/filing?token=abc', 'excerpt':'Public filing'}]})
        result = read_local(self.project)
        text = json.dumps(result)
        for value in (secret, 'PRIVATE-ACCOUNT', 'DO-NOT-EXPORT', 'private@example.com', '?token='):
            self.assertNotIn(value, text)
        self.assertEqual(result['dossiers'][0]['fundamentals']['metrics']['cash']['value'], 123)

    def test_events_have_time_and_only_latest_200(self):
        for n in range(205):
            self.db.execute('INSERT INTO events VALUES(?,?,?)', (n, '2026-10-12T00:00:00Z', json.dumps({'message':str(n)})))
        self.db.commit()
        events = read_local(self.project)['events']
        self.assertEqual(len(events),200)
        self.assertEqual(events[0]['id'],204)
        self.assertIn('at',events[0])

    def test_scan_internal_copies_removed_but_complete_dossier_and_progress_preserved(self):
        self.put('scan', 'latest', {'finalist_packets': {'SECRET_INTERNAL': 'duplicate'},
                 'finalist_results': {'duplicate': True}, 'covered_symbols':['X'],
                 'finalists_pending':['TEST'], 'finalist_retry_after':'2026-10-12T15:00:00Z',
                 'covered_count':3828, 'current_symbol':'TEST'})
        self.put('thesis', 'TEST', {'symbol':'TEST', 'failure_http_status':429,
                 'failure_phase':'http', 'failure_provider_code':'insufficient_quota',
                 'evidence':[{'title':'Original evidence','excerpt':'Public filing'}]})
        self.put('runtime', 'research', {'heartbeat_at':'2026-10-12T14:59:59Z',
                 'stage':'analyze','thread_alive':True,'current_symbol':'TEST','api_key':'never_export'})
        value = read_local(self.project)
        self.assertNotIn('finalist_packets', value['scan'])
        self.assertNotIn('finalist_results', value['scan'])
        self.assertNotIn('covered_symbols', value['scan'])
        self.assertEqual(value['scan']['covered_count'],3828)
        self.assertEqual(value['scan']['finalists_pending'],['TEST'])
        self.assertEqual(value['dossiers'][0]['failure_http_status'],429)
        self.assertEqual(value['dossiers'][0]['evidence'][0]['title'],'Original evidence')
        self.assertEqual(value['runtime']['research']['current_symbol'],'TEST')
        self.assertNotIn('api_key',value['runtime']['research'])
        value['scan']['finalist_packets']={'nested':True}
        self.assertNotIn('finalist_packets',validate(value)['scan'])

    def test_sec_diagnostics_export_safe_endpoint_and_times(self):
        cache = self.project / 'data' / 'sec_cache'
        cache.mkdir()
        (cache / 'access_state.json').write_text(json.dumps({'requests':3,'status':'network_error',
            'last_endpoint':'https://data.sec.gov/path?token=private', 'error_kind':'dns',
            'last_request':1720000000,'last_success':1719999999,'pause_until':0,
            'SEC_USER_AGENT':'private@example.com'}))
        state = read_local(self.project)['sec_health']
        self.assertEqual(state['last_endpoint'],'https://data.sec.gov/path')
        self.assertEqual(state['error_kind'],'dns')
        self.assertEqual(state['last_success'],1719999999)
        self.assertNotIn('SEC_USER_AGENT',state)

    def test_transport_only_beta_endpoints_no_broker(self):
        snapshot = read_local(self.project)
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, size): return b'{"ok":true}'
        with patch('beta_panel.transport.request.build_opener') as opener:
            opener.return_value.open.return_value = Reply()
            rpc('https://example.supabase.co','sb_publishable_test','x'*43,snapshot=snapshot)
            req = opener.return_value.open.call_args.args[0]
            self.assertTrue(req.full_url.endswith('/rest/v1/rpc/vt_beta_write'))
            self.assertEqual(json.loads(req.data)['p_snapshot']['paper'],True)
        for url in ('http://example.supabase.co','https://evil.example','https://example.supabase.co/redirect'):
            with self.assertRaises(LinkError):
                rpc(url,'sb_publishable_test','x'*43,snapshot=snapshot)

    def test_rejects_nonpaper_corrupt_and_oversize_instead_of_partial_data(self):
        raw = read_local(self.project)
        with self.assertRaises(SnapshotError): validate({**raw,'paper':False})
        with self.assertRaises(SnapshotError): validate({**raw,'positions':{}})
        with self.assertRaises(SnapshotError): validate({**raw,'observed_at':'invalid'})
        raw['validations']=[{'name':'x'*8_000_001}]
        with self.assertRaises(SnapshotError): validate(raw)

    def test_nested_ui_empty_and_populated_records(self):
        from streamlit.testing.v1 import AppTest
        raw = read_local(self.project)
        def app(snapshot):
            from beta_panel.ui import render
            render(snapshot)
        at = AppTest.from_function(app, args=(raw,)).run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual([tab.label for tab in at.tabs], ['Overview','Research','Positions','Activity'])
        raw['dossiers']=[{'id':'t','symbol':'TEST','direction':'call','company':'Test Company',
            'research_scorecard':{'research_points':85,'components':[]},
            'evidence':[{'title':'Filing','url':'https://example.com/report','excerpt':'Evidence'}],
            'fundamentals':{'metrics':{'cash':{'value':123,'unit':'USD'}}}}]
        raw['positions']=[{'id':'p','symbol':'TEST','state':'open','direction':'call','qty':1,'entry_cost':'1000'}]
        raw['orders']=[{'symbol':'TEST','status':'filled','qty':1}]
        at = AppTest.from_function(app, args=(raw,)).run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any(e.label == 'Open a complete research dossier' for e in at.selectbox))
        at.multiselect[0].set_value(['put']).run()
        self.assertEqual(len(at.exception),0)

    def test_installer_preserves_other_files_and_backs_up_only_ui(self):
        from install_beta_dashboard import install, OLD, NEW
        target = self.project / 'Coding'
        target.mkdir()
        original = 'def render():\n    if True:\n' + OLD + '\n'
        (target / 'dashboard.py').write_text('# existing dashboard')
        (target / 'dashboard_views.py').write_text(original)
        (target / '.env').write_text('PRIVATE=unchanged')
        (target / 'run_paper.py').write_text('# untouched runner')
        backup = install(Path(__file__).parent, target)
        self.assertEqual((backup / 'dashboard_views.py').read_text(), original)
        self.assertIn(NEW, (target / 'dashboard_views.py').read_text())
        self.assertEqual((target / '.env').read_text(), 'PRIVATE=unchanged')
        self.assertEqual((target / 'run_paper.py').read_text(), '# untouched runner')
        install(Path(__file__).parent, target)  # reinstallation is safe
        self.assertEqual((target / 'dashboard_views.py').read_text().count('render_beta(d)'), 1)
        (target / 'dashboard_views.py').write_text('# different version')
        with self.assertRaises(ValueError): install(Path(__file__).parent, target)
        self.assertEqual((target / 'dashboard_views.py').read_text(), '# different version')

    def test_unavailable_beta_does_not_stop_sibling_dashboard(self):
        from streamlit.testing.v1 import AppTest
        def app():
            from types import SimpleNamespace
            import streamlit as st
            from beta_panel.integration import render_beta
            d = SimpleNamespace(BASE='/unavailable', setting=lambda key, default='': default)
            with st.tabs(['Existing dashboard', 'Beta Research'])[1]:
                render_beta(d)
            st.success('Existing dashboard still renders')
        at = AppTest.from_function(app).run(timeout=15)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.success[0].value, 'Existing dashboard still renders')


if __name__ == '__main__':
    unittest.main()
