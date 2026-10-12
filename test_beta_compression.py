"""Lossless Beta wire transport and hostile-envelope regressions; no network."""
import base64
from copy import deepcopy
import hashlib
import json
import random
import unittest
from unittest.mock import patch
import zlib

from beta_panel.snapshot import CONFIG, OBJECTS, SECTIONS, validate
import telemetry_link as link


def beta():
    return dict(schema=1, paper=True, observed_at='2026-10-12T14:30:00+00:00',
                config=dict(CONFIG), **{key: [] for key in SECTIONS},
                **{key: {} for key in OBJECTS})


def envelope(document):
    return dict(schema=1, paper=True, observed_at='2026-10-12T14:30:00+00:00',
                reports={'hero': {'paper': True, 'health': 'SCANNING',
                                  'heartbeat': '2026-10-12T14:29:59+00:00'}}, beta=document)


def large_beta():
    value = beta()
    value['positions'] = [{'id': str(n), 'symbol': 'TEST', 'qty': n+1, 'state': state}
                          for n, state in enumerate(('open', 'opening', 'closing', 'quarantine', 'closed'))]
    value['orders'] = [{'id': str(n), 'qty': n+1, 'status': 'filled' if n % 2 else 'new'} for n in range(100)]
    value['events'] = [{'id': n, 'message': 'Research review '+str(n)} for n in range(200)]
    value['dossiers'] = [{'id': str(n), 'symbol': 'TEST'+str(n),
                         'summary': ('Financial evidence and company thesis. ' * 1500),
                         'fundamentals': {'quarterly': {'revenue': [{'value': n+1, 'unit': 'USD'}]}},
                         'evidence': [{'url': 'https://www.sec.gov/Archives/test'+str(n), 'excerpt': 'Original public source'}]}
                        for n in range(30)]
    value['validations'] = [{'name': 'Paper validation record', 'status': 'UNVALIDATED'}]
    value['entry_checks'] = [{'thesis_id': str(n), 'reason': 'Awaiting all checks'} for n in range(30)]
    return value


class BetaCompressionTests(unittest.TestCase):
    def test_complete_large_portfolio_and_research_survive_lossless_wire(self):
        raw = large_beta()
        original = validate(raw)
        self.assertGreater(len(json.dumps(original).encode()), link.SNAPSHOT_BUDGET)
        wire = link.sanitize_snapshot(envelope(raw))
        self.assertIsNone(wire['beta'])
        self.assertEqual(wire['beta_compressed']['encoding'], 'zlib-base64-v1')
        self.assertIsNone(wire['beta_error'])
        self.assertLess(len(json.dumps(wire, ensure_ascii=False).encode()), link.SNAPSHOT_BUDGET)
        decoded = link.sanitize_snapshot(wire, wire=False)
        self.assertEqual(decoded['beta'], original)
        self.assertEqual(len(decoded['beta']['dossiers']), 30)
        self.assertEqual(len(decoded['beta']['positions']), 5)
        self.assertEqual(len(decoded['beta']['events']), 200)
        self.assertEqual(decoded['reports']['hero']['health'], 'SCANNING')

    def test_wire_and_logical_sanitization_are_idempotent(self):
        wire = link.sanitize_snapshot(envelope(large_beta()))
        self.assertEqual(wire, link.sanitize_snapshot(deepcopy(wire)))
        logical = link.sanitize_snapshot(wire, wire=False)
        self.assertEqual(logical, link.sanitize_snapshot(deepcopy(logical), wire=False))
        self.assertEqual(wire, link.sanitize_snapshot(logical))

    def test_legacy_small_uncompressed_reports_stay_readable(self):
        raw = beta()
        raw['dossiers'] = [{'id': 'a', 'symbol': 'AAPL', 'summary': 'Existing research'}]
        wire = link.sanitize_snapshot(envelope(raw))
        self.assertIsNone(wire['beta_compressed'])
        self.assertEqual(wire['beta'], validate(raw))
        self.assertEqual(wire, link.sanitize_snapshot(wire))

    def test_oversize_incompressible_beta_is_not_partially_presented(self):
        raw = beta()
        raw['dossiers'] = [{'id': 'a', 'summary': base64.b64encode(random.Random(1).randbytes(900_000)).decode()}]
        wire = link.sanitize_snapshot(envelope(raw))
        self.assertIsNone(wire['beta'])
        self.assertIsNone(wire['beta_compressed'])
        self.assertEqual(wire['beta_error'], 'BETA_TOO_LARGE')
        self.assertEqual(wire['reports']['hero']['health'], 'SCANNING')

    def test_corruption_length_trailing_or_truncated_stream_is_beta_only_failure(self):
        original = link.sanitize_snapshot(envelope(large_beta()))
        packed = original['beta_compressed']
        variants = []
        for key, value in [('sha256', '0'*64), ('raw_bytes', packed['raw_bytes']-1),
                           ('raw_bytes', True), ('payload', '%invalid!'), ('encoding', 'unknown')]:
            changed = dict(packed); changed[key] = value; variants.append(changed)
        data = base64.b64decode(packed['payload'])
        for data in (data[:-1], data+b'trailing', data+zlib.compress(b'second stream')):
            changed = dict(packed); changed['payload'] = base64.b64encode(data).decode(); variants.append(changed)
        for changed in variants:
            with self.subTest(changed_keys={k for k in changed if changed[k] != packed[k]}):
                raw = deepcopy(original); raw['beta_compressed'] = changed
                result = link.sanitize_snapshot(raw, wire=False)
                self.assertIsNone(result['beta'])
                self.assertEqual(result['beta_error'], 'BETA_INVALID')
                self.assertEqual(result['reports']['hero']['health'], 'SCANNING')

    def test_advertised_and_encoded_caps_checked_before_decompression(self):
        valid = link._beta_packed(validate(beta()))
        for key, value in [('raw_bytes', link.BETA_LOGICAL_MAX_BYTES+1), ('raw_bytes', -1),
                           ('payload', 'A'*(link.SNAPSHOT_BUDGET+1))]:
            altered = {**valid, key: value}
            with patch.object(link.zlib, 'decompressobj') as decompress:
                with self.assertRaises(ValueError):
                    link._beta_unpacked(altered)
                decompress.assert_not_called()

    def test_expansion_bomb_is_bounded_by_advertised_length(self):
        payload = b'A'*(link.BETA_LOGICAL_MAX_BYTES+1)
        packed = {'encoding': link.BETA_PACKED_ENCODING, 'raw_bytes': 16,
                  'sha256': hashlib.sha256(payload).hexdigest(),
                  'payload': base64.b64encode(zlib.compress(payload, 9)).decode()}
        with self.assertRaises(ValueError):
            link._beta_unpacked(packed)

    def test_raw_logical_limit_and_ambiguous_payload_are_rejected(self):
        raw = beta(); raw['dossiers'] = [{'summary': 'x'*(link.BETA_LOGICAL_MAX_BYTES+1)}]
        result = link.sanitize_snapshot(envelope(raw))
        self.assertEqual(result['beta_error'], 'BETA_INVALID')
        raw = envelope(beta()); raw['beta_compressed'] = link._beta_packed(validate(beta()))
        self.assertEqual(link.sanitize_snapshot(raw)['beta_error'], 'BETA_INVALID')

    def test_fetch_remote_decodes_and_rpc_write_keeps_bounded_wire(self):
        original = large_beta()
        raw = envelope(original)
        wire = link.sanitize_snapshot(raw)
        response = {'received_at': '2026-10-12T14:30:01+00:00', 'snapshot': wire}
        with patch.object(link, 'rpc', return_value=response):
            fetched = link.fetch_remote('https://abc.supabase.co', 'sb_publishable_test', 'a'*43)
        self.assertEqual(fetched['snapshot']['beta'], validate(original))

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'{"ok":true}'

        with patch.object(link.request, 'build_opener') as opener:
            opener.return_value.open.return_value = Reply()
            link.rpc('https://abc.supabase.co', 'sb_publishable_test', 'vt_write', 'a'*43, raw)
            request = opener.return_value.open.call_args.args[0]
            body = json.loads(request.data)
            self.assertEqual(body['p_snapshot'], wire)
            self.assertLess(len(request.data), link.MAX_BYTES)
            self.assertLess(len(json.dumps(body['p_snapshot'], ensure_ascii=False).encode()), link.SNAPSHOT_BUDGET)

    def test_existing_beta_tabs_and_stock_dossiers_render_after_compressed_read(self):
        from streamlit.testing.v1 import AppTest
        wire = link.sanitize_snapshot(envelope(large_beta()))

        def app(snapshot):
            from types import SimpleNamespace
            from telemetry_link import sanitize_snapshot
            from beta_panel.integration import render_beta
            d = SimpleNamespace(BASE='/unused', setting=lambda key, default='': 'remote' if key in ('TELEMETRY_MODE', 'BETA_DASHBOARD_MODE') else default,
                                remote_report=lambda: {'snapshot': sanitize_snapshot(snapshot, wire=False)})
            render_beta(d)

        at = AppTest.from_function(app, args=(wire,)).run(timeout=20)
        self.assertEqual(len(at.exception), 0)
        self.assertTrue({'Overview', 'Research', 'Positions', 'Activity'}.issubset({tab.label for tab in at.tabs}))
        dossier = next(item for item in at.selectbox if item.label == 'Open a complete research dossier')
        self.assertEqual(len(dossier.options), 30)


if __name__ == '__main__':
    unittest.main()
