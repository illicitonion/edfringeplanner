from collections import defaultdict

import pytz

from config import Config
from db import cursor
from fetcher import check_soldout_for_single_time, fetch_multitime


def main():
    shows = defaultdict(set)
    singletime_shows = set()
    multitime_shows = set()

    config = Config.from_env()
    with cursor(config) as cur:
        cur.execute("SELECT show_id, datetime_utc FROM performances")
        rows = cur.fetchall()
        for show_id, datetime_utc in rows:
            shows[show_id].add(
                datetime_utc.astimezone(pytz.timezone("Europe/London")).time()
            )
        for show, times in shows.items():
            if len(times) == 1:
                singletime_shows.add(show)
            else:
                multitime_shows.add(show)
        for show_id in singletime_shows:
            check_soldout_for_single_time(cur, show_id)
        for show_id in multitime_shows:
            fetch_multitime(cur, show_id, "01-08-2019")


if __name__ == "__main__":
    main()
