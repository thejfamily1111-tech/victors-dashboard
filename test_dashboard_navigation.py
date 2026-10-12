"""Exercise real tab widget events and reruns without providers or broker calls."""
import unittest

from streamlit.testing.v1 import AppTest


APP = '''
import streamlit as st
from beta_panel.views import persistent_tabs
@st.fragment(run_every='15s')
def body():
    qqq, beta = persistent_tabs(['QQQ Terminal', 'Beta Research'], key='vt_terminal_tab')
    with qqq:
        one, two = persistent_tabs(['Overview', 'Teams & activity'], key='vt_qqq_tab')
        with one: st.text_input('Chart symbol', value='QQQ', key='chart_symbol')
        with two: st.write('Teams')
    with beta:
        one, two = persistent_tabs(['Overview', 'Research'], key='vt_beta_tab')
        with one: st.write('Beta overview')
        with two:
            a, b = persistent_tabs(['Decision & contract', 'Sources & opposing case'], key='vt_beta_dossier_tab')
            with a: st.write('Decision')
            with b: st.write('Sources')
body()
'''


def select_tabs(app, choices):
    # AppTest has no Tab.select API. Send the same string-valued widget event
    # as the browser so the actual on_change callback, not a mock, runs.
    states = app._tree.get_widget_states()
    for node in app.get('tab_container'):
        identifier = node.proto.tab_container.id
        for key, label in choices.items():
            if identifier.endswith('-' + key):
                states.widgets.add(id=identifier, string_value=label)
    return app._run(states)


def selected_indices(app):
    return {node.proto.tab_container.id.rsplit('-', 1)[-1]: node.proto.tab_container.default_tab_index
            for node in app.get('tab_container')}


class NavigationTests(unittest.TestCase):
    def test_selection_survives_refresh_and_preserves_other_widgets(self):
        app = AppTest.from_string(APP).run()
        app.text_input(key='chart_symbol').set_value('AAPL').run()
        choices = {'vt_terminal_tab': 'Beta Research', 'vt_beta_tab': 'Research',
                   'vt_beta_dossier_tab': 'Sources & opposing case', 'vt_qqq_tab': 'Teams & activity'}
        select_tabs(app, choices)
        self.assertFalse(app.exception)
        self.assertEqual(selected_indices(app), {key: 1 for key in choices})
        for _ in range(3):
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(selected_indices(app), {key: 1 for key in choices})
            self.assertEqual(app.text_input(key='chart_symbol').value, 'AAPL')
        for key, value in choices.items():
            self.assertEqual(app.session_state[key], value)
            self.assertEqual(app.query_params[key], value)
        select_tabs(app, {'vt_terminal_tab': 'QQQ Terminal'})
        app.run()
        self.assertEqual(app.session_state['vt_terminal_tab'], 'QQQ Terminal')
        self.assertEqual(app.session_state['vt_qqq_tab'], 'Teams & activity')
        self.assertEqual(app.session_state['vt_beta_dossier_tab'], 'Sources & opposing case')

    def test_browser_reload_restores_tabs_from_fixed_label_url_values(self):
        first = AppTest.from_string(APP).run()
        select_tabs(first, {'vt_terminal_tab': 'Beta Research', 'vt_beta_tab': 'Research'})
        reloaded = AppTest.from_string(APP)
        reloaded.query_params.update(first.query_params)
        reloaded.run()
        self.assertFalse(reloaded.exception)
        self.assertEqual(reloaded.session_state['vt_terminal_tab'], 'Beta Research')
        self.assertEqual(reloaded.session_state['vt_beta_tab'], 'Research')
        self.assertNotIn('authenticated', reloaded.session_state)

    def test_invalid_url_label_does_not_create_a_new_view(self):
        app = AppTest.from_string(APP)
        app.query_params['vt_terminal_tab'] = ['Unknown destination']
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['vt_terminal_tab'], 'QQQ Terminal')


if __name__ == '__main__':
    unittest.main()
