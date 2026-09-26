"""QQQ CALL rules. BB rejection -> EMA confirmation -> structural room.
Paper-test assumptions, not optimized. See STRATEGY.md for exact formulas.
Rule methods propose actions; run_paper.py handles actual simulated orders.
RSI constructor arguments retained for compatibility; RSI is context only.
"""

class HeroCallExecutor:
    MAG7 = ('MSFT', 'AAPL', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA')

    def __init__(self, ticker='QQQ', state=None, rsi_min=50.0, rsi_max=70.0):
        if ticker != 'QQQ':
            raise ValueError('HERO supports QQQ only')
        self.rsi_min = self._num(rsi_min)
        self.rsi_max = self._num(rsi_max)
        if not 0 <= self.rsi_min < self.rsi_max <= 100:
            raise ValueError('RSI limits must satisfy 0 <= min < max <= 100')
        self.ticker = ticker
        self.state = {'version': 1, 'submitted_signals': [], 'positions': {}}
        if state is not None:
            import copy
            if state.get('version') != 1 or not isinstance(state.get('positions'), dict) or not isinstance(state.get('submitted_signals'), list):
                raise ValueError('Invalid HERO state')
            self.state = copy.deepcopy(state)
        self.last_entry_decision = None
        self.last_exit_decision = None

    @staticmethod
    def _num(value):
        import math
        if isinstance(value, bool):
            raise ValueError('Boolean is not a price')
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Non-finite value')
        return result

    @staticmethod
    def _time(value):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError('Timestamp needs timezone')
        return result.astimezone(ZoneInfo('America/New_York'))

    @classmethod
    def _fresh(cls, timestamp, now, seconds):
        stamp = cls._time(timestamp)
        age = (now - stamp).total_seconds()
        if not 0 <= age <= seconds:
            raise ValueError('Stale or future data')
        return stamp

    @classmethod
    def calculate_rsi(cls, completed_closes, period=14):
        """Wilder RSI: SMA seed, then recursive smoothing; oldest close first.
        Caller must exclude forming candles and use a consistent history window.
        Returns None before period+1 closes. Flat history returns neutral 50.
        """
        if isinstance(period, bool) or not isinstance(period, int) or period < 1:
            raise ValueError('Invalid RSI period')
        closes = [cls._num(x) for x in completed_closes]
        if any(x <= 0 for x in closes):
            raise ValueError('Invalid RSI close')
        if len(closes) < period + 1:
            return None
        changes = [b-a for a,b in zip(closes,closes[1:])]
        gain = sum(max(x,0) for x in changes[:period]) / period
        loss = sum(max(-x,0) for x in changes[:period]) / period
        for change in changes[period:]:
            gain = (gain*(period-1)+max(change,0))/period
            loss = (loss*(period-1)+max(-change,0))/period
        if gain == 0 and loss == 0:
            return 50.0
        if loss == 0:
            return 100.0
        return 100.0-100.0/(1.0+gain/loss)

    def export_state(self):
        import copy
        return copy.deepcopy(self.state)

    def evaluate_entry(self, data, mag_7_status=None, now=None):
        from strategy_formula import evaluate
        return evaluate(self, data, 'CALL', now)

    def check_call_execution_triggers(self, market_data_5m, mag_7_status):
        """Compatibility boolean wrapper; see last_entry_decision for reasons."""
        return self.evaluate_entry(market_data_5m, mag_7_status)['action'] == 'BUY_CALL_SIGNAL'

    def mark_entry_submitted(self, signal_id):
        if not signal_id or not signal_id.startswith('QQQ-CALL-'):
            raise ValueError('Invalid signal ID')
        if signal_id not in self.state['submitted_signals']:
            self.state['submitted_signals'].append(signal_id)

    def register_position(self, position_id, quantity, average_fill):
        """Register actual filled quantity once entry remainder is terminal."""
        qty = self._num(quantity); price = self._num(average_fill)
        if not position_id or qty < 1 or qty != int(qty) or price <= 0:
            raise ValueError('Invalid filled position')
        value = {'original_qty': int(qty), 'remaining_qty': int(qty), 'entry_price': price,
                 'scale_target': int(qty)//2 if qty >= 2 else 0, 'scale_filled': 0,
                 'scale_requested': False, 'runner_active': False, 'close_reason': None,
                 'exit_fills': {}}
        if position_id in self.state['positions']:
            existing = self.state['positions'][position_id]
            if existing['original_qty'] != qty or existing['entry_price'] != price:
                raise ValueError('Position identity conflict')
            return
        self.state['positions'][position_id] = value

    def evaluate_exit(self, position_id, data, now=None):
        from datetime import datetime, timezone
        p = self.state['positions'].get(position_id)
        if p is None: return {'action': 'DATA_UNAVAILABLE', 'quantity': 0, 'reason': 'POSITION_NOT_REGISTERED'}
        def decision(action, reason, qty=0):
            result = {'action': action, 'quantity': qty, 'reason': reason}
            self.last_exit_decision = result
            return result
        if p['remaining_qty'] == 0: return decision('HOLD', 'ALREADY_CLOSED')
        if data.get('exit_pending') is True: return decision('HOLD', 'EXIT_ORDER_PENDING')
        if data.get('force_exit') is True: p['close_reason'] = 'SESSION_OR_EXECUTOR_FLATTEN'
        if p['close_reason']: return decision('CLOSE_ALL', p['close_reason'], p['remaining_qty'])
        try:
            now = self._time(now or datetime.now(timezone.utc))
            from strategy_formula import technical_exit
            reason = technical_exit(self, p, data, 'CALL', now)
            if reason:
                p['close_reason'] = reason
                return decision('CLOSE_ALL', reason, p['remaining_qty'])
            self._fresh(data['option_quote_timestamp'], now, 30)
            bid = self._num(data['option_bid'])
            if bid < 0: raise ValueError('Negative option bid')
            pnl = bid / p['entry_price'] - 1
            # Fresh premium risk can trigger even if the candle feed is unavailable.
            reason = 'PREMIUM_STOP_20_PERCENT' if bid <= .8*p['entry_price'] else None
            if p['runner_active'] and bid <= p['entry_price']: reason = 'RUNNER_BREAK_EVEN_TRIGGER'
            if reason:
                p['close_reason'] = reason
                return decision('CLOSE_ALL', reason, p['remaining_qty'])
            end = self._fresh(data['bar_end'], now, 330)
            if data.get('bar_complete') is not True or end.minute % 5 or end.second or end.microsecond:
                raise ValueError('Incomplete candle')
            close, ema9, ema21 = [self._num(data[k]) for k in ('price_close','ema_9_5m','ema_21_5m')]
            if min(close, ema9, ema21) <= 0: raise ValueError('Invalid price')
            reason = 'CLOSE_BELOW_EMA21' if close < ema21 else None
            if p['runner_active'] and close < ema9: reason = 'RUNNER_CLOSE_BELOW_EMA9'
            if reason:
                p['close_reason'] = reason
                return decision('CLOSE_ALL', reason, p['remaining_qty'])
            if p['runner_active']: return decision('HOLD', 'RUNNER_ACTIVE')
            # A latched target survives price retreats while a partial fill is reconciled.
            if not p['scale_requested']:
                stretched = False
                if all(k in data for k in ('upper_bband','lower_bband','previous_bb_width')):
                    upper, lower, previous_width = [self._num(data[k]) for k in ('upper_bband','lower_bband','previous_bb_width')]
                    if not 0 < lower < upper or previous_width <= 0: raise ValueError('Invalid bands')
                    stretched = close > upper and upper-lower >= 1.10*previous_width
                if pnl >= .30 or stretched:
                    if p['original_qty'] == 1:
                        p['close_reason'] = 'TAKE_PROFIT'
                        return decision('CLOSE_ALL','TAKE_PROFIT',1)
                    p['scale_requested'] = True
            if p['scale_requested']:
                return decision('SCALE_OUT_50','FIRST_TARGET', min(p['remaining_qty'],p['scale_target']-p['scale_filled']))
            return decision('HOLD','NO_EXIT_TRIGGER')
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return decision('DATA_UNAVAILABLE','INVALID_EXIT_DATA: '+str(exc))

    def confirm_exit_fill(self, position_id, order_id, cumulative_filled, purpose):
        """Idempotent broker fill update. purpose is SCALE_OUT_50 or CLOSE_ALL."""
        p = self.state['positions'][position_id]
        qty = self._num(cumulative_filled)
        if not order_id or qty < 0 or qty != int(qty) or purpose not in {'SCALE_OUT_50','CLOSE_ALL'}:
            raise ValueError('Invalid fill report')
        previous = p['exit_fills'].get(order_id, {'quantity':0,'purpose':purpose})
        if previous['purpose'] != purpose: raise ValueError('Order purpose changed')
        delta = int(qty)-previous['quantity']
        if delta < 0 or delta > p['remaining_qty']: raise ValueError('Invalid cumulative fill')
        if purpose == 'SCALE_OUT_50' and (not p['scale_requested'] or p['scale_filled']+delta > p['scale_target']):
            raise ValueError('Scale fill exceeds requested quantity')
        p['remaining_qty'] -= delta
        if purpose == 'SCALE_OUT_50': p['scale_filled'] += delta
        p['runner_active'] = p['scale_target'] > 0 and p['scale_filled'] == p['scale_target']
        p['exit_fills'][order_id] = {'quantity':int(qty),'purpose':purpose}

    def monitor_exit_management(self, position_data):
        """Compatibility action string; register_position and report fills first."""
        return self.evaluate_exit(position_data.get('position_id'),position_data)['action']


if __name__ == '__main__':
    print('HERO rule module loaded. No broker connection or automatic trading loop is configured.')
