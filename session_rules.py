"""One regular-session entry window shared by strategies and coordinator."""
from datetime import time, timedelta

ENTRY_START = time(9, 45)
ENTRY_STOP = time(15, 40)
ENTRY_WINDOW_LABEL = '09:45-15:40 ET (new entries stop before 15:45 flatten)'


def entry_cutoff(current, closing=None):
    cutoff = current.replace(hour=15, minute=40, second=0, microsecond=0)
    return min(cutoff, closing-timedelta(minutes=20)) if closing else cutoff


def entry_allowed(end, current):
    # The coordinator additionally caps early-close days with the exchange calendar.
    return (end.date() == current.date() and current.weekday() < 5
            and ENTRY_START <= end.time().replace(tzinfo=None) < ENTRY_STOP
            and ENTRY_START <= current.time().replace(tzinfo=None) < ENTRY_STOP)
