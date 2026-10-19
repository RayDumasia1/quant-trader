"""Versioned Nasdaq regular-session calendar and conservative data availability."""
from datetime import timedelta

import pandas as pd
import pandas_market_calendars as mcal

CALENDAR = 'NASDAQ'
PUBLICATION_LAG_MINUTES = 5


def schedule(start, end):
    frame = mcal.get_calendar(CALENDAR).schedule(start_date=start, end_date=end)
    return [{'session': day.date().isoformat(),
             'open_at': row.market_open.isoformat(),
             'close_at': row.market_close.isoformat(),
             'available_at': (row.market_close + timedelta(minutes=PUBLICATION_LAG_MINUTES)).isoformat()}
            for day, row in frame.iterrows()]


def utc_timestamp(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError('Timezone-aware timestamps are required')
    return stamp.tz_convert('UTC')


def latest_session(as_of):
    stamp = utc_timestamp(as_of)
    days = schedule((stamp - pd.Timedelta(days=30)).date(), stamp.date())
    return next(row for row in reversed(days) if utc_timestamp(row['available_at']) <= stamp)
