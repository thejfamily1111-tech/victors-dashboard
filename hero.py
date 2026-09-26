"""QQQ CALL rule engine. No network, broker orders, or automatic trading loop.

Entry: fresh close across ORB15 high; close > EMA9 > EMA21; BB position <= .85;
4/7 named Mag-7 green; completed, timestamped inputs no older than 180 seconds.
GREEN is supplied by caller, using one consistent prior-session-close baseline.

Exits: -20% from actual average option fill (fixed, not trailing), completed
close below EMA21; +30% or defined BB extension scales floor(original_qty/2).
After that quantity is FILLED, remaining contracts use an option break-even
trigger and completed close below EMA9. One contract closes fully at target.
BB extension: close > upper band AND width >= 1.10 * previous completed width.
This 10% expansion definition is an explicit unvalidated design assumption.

Caller supplies fresh option bid and aware timestamps; timestamps label candle
END. First post-ORB entry can be 09:50 ET. No new entry at/after 15:00 ET;
force_exit must be supplied for session flattening/early closes by an executor.

RSI entry filter: 50 < QQQ RSI(14, Wilder, completed 5m) < 70.
Supply rsi_14_5m and rsi_bar_end matching bar_end. Missing, NaN, out-of-range or
mismatched RSI blocks new entries. calculate_rsi computes the latest RSI from
oldest-to-newest completed closes. Use consistent prior-session warmup history;
14 changes is only the mathematical minimum, not full convergence.
RSI thresholds are configurable initial assumptions, not optimized settings.
RSI never suppresses exits. No dashboard or data-feed wiring is included here.
Both engines require fresh vic_permission with light/checked_at/valid_until.

Durability/execution contract:
- evaluate_entry/evaluate_exit propose actions; they never submit orders.
- Call mark_entry_submitted only after recording broker submission intent.
- An executor must cancel/reconcile entry remainder before exit orders.
- Persist export_state atomically after every state mutation; restore on restart.
- Report actual cumulative fills via confirm_exit_fill; a signal is NOT a fill.
- With an exit pending, set exit_pending=True to prevent a second order.
- Invalid/stale exit data returns DATA_UNAVAILABLE; executor must handle it.
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

    def evaluate_mag_7_filter(self, mag_7_status):
        return (all(mag_7_status.get(s) in {'GREEN', 'RED', 'FLAT'} for s in self.MAG7)
                and sum(mag_7_status[s] == 'GREEN' for s in self.MAG7) >= 4)

    def evaluate_bollinger_filter(self, price, lower_band, middle_band, upper_band):
        try:
            price, low, mid, high = map(self._num, (price, lower_band, middle_band, upper_band))
            return 0 < low < mid < high and price > 0 and (price-low)/(high-low) <= .85
        except (ValueError, TypeError):
            return False

    def evaluate_entry(self, data, mag_7_status, now=None):
        from datetime import datetime, timedelta, timezone
        result = {'action': 'WAIT', 'reasons': [], 'signal_id': None}
        try:
            now = self._time(now or datetime.now(timezone.utc))
            # Entry permission is fail-closed. It never suppresses risk exits.
            permission = data.get('vic_permission')
            if not isinstance(permission, dict):
                result['reasons'].append('VIC_PERMISSION_MISSING')
            else:
                if permission.get('light') != 'GREEN':
                    result['reasons'].append('VIC_RED_OR_UNKNOWN')
                try:
                    self._fresh(permission['checked_at'], now, 60)
                    if self._time(permission['valid_until']) <= now:
                        raise ValueError('Expired permission')
                except (KeyError, ValueError, TypeError):
                    result['reasons'].append('VIC_PERMISSION_STALE_OR_INVALID')
            end = self._fresh(data['bar_end'], now, 180)
            prev_end = self._time(data['previous_bar_end'])
            mag_end = self._fresh(data['mag7_bar_end'], now, 180)
            orb_end = self._time(data['orb_end'])
            if (data.get('bar_complete') is not True or end.minute % 5 or end.second or end.microsecond
                or end - prev_end != timedelta(minutes=5) or mag_end != end):
                raise ValueError('Incomplete or mismatched candles')
            if (data.get('orb_locked') is not True or orb_end.date() != end.date()
                or orb_end.strftime('%H:%M:%S') != '09:45:00' or end <= orb_end):
                raise ValueError('ORB15 not locked or no post-range candle')
            if now.date() != end.date() or now.weekday() >= 5 or not '09:50' <= now.strftime('%H:%M') < '15:00':
                result['reasons'].append('OUTSIDE_ENTRY_WINDOW')
            close, previous, orb, ema9, ema21 = [self._num(data[k]) for k in
                ('price_close', 'previous_close', 'orb_high', 'ema_9_5m', 'ema_21_5m')]
            if min(close, previous, orb, ema9, ema21) <= 0:
                raise ValueError('Invalid price')
            if not previous <= orb < close: result['reasons'].append('NO_FRESH_ORB_BREAKOUT')
            if not close > ema9 > ema21: result['reasons'].append('PRICE_EMA_ALIGNMENT_FAILED')
            if not self.evaluate_bollinger_filter(close, data['lower_bband'], data['middle_bband'], data['upper_bband']):
                result['reasons'].append('BOLLINGER_FILTER_FAILED')
            rsi = self._num(data['rsi_14_5m'])
            if not 0 <= rsi <= 100 or self._time(data['rsi_bar_end']) != end:
                raise ValueError('Invalid or mismatched RSI')
            result['rsi_14_5m'] = rsi
            result['rsi_limits'] = [self.rsi_min, self.rsi_max]
            if not self.rsi_min < rsi < self.rsi_max:
                result['reasons'].append('RSI_OUTSIDE_ENTRY_RANGE')
            if not self.evaluate_mag_7_filter(mag_7_status): result['reasons'].append('MAG7_FILTER_FAILED_OR_MISSING')
            signal = f'QQQ-CALL-{end.isoformat()}'
            result['signal_id'] = signal
            if signal in self.state['submitted_signals']: result['reasons'].append('SIGNAL_ALREADY_SUBMITTED')
            if any(p['remaining_qty'] > 0 for p in self.state['positions'].values()):
                result['reasons'].append('POSITION_ALREADY_OPEN')
            if not result['reasons']: result['action'] = 'BUY_CALL_SIGNAL'
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            result['reasons'].append('INVALID_ENTRY_DATA: ' + str(exc))
        self.last_entry_decision = result
        return result

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
