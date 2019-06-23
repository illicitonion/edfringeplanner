import csv
import datetime
import sys

import psycopg2
import pytz
import requests

from config import Config
from db import cursor


def parse_time(human):
    parts = human.split()
    if len(parts) % 2 != 0:
        raise ValueError(
            "Could not parse human-readable time {} because odd number of tokens".format(
                human
            )
        )

    delta = datetime.timedelta()
    for (index, unit) in enumerate(parts[1::2]):
        value = int(parts[2 * index])
        if unit == "hour" or unit == "hours":
            delta += datetime.timedelta(hours=value)
        elif unit == "minute" or unit == "minutes":
            delta += datetime.timedelta(minutes=value)
        else:
            raise ValueError(
                "Could not parse human-readable time {} because of unknown units {}".format(
                    human, unit
                )
            )

    return str(delta)


def lookup_venue_id(cur: psycopg2.extensions.cursor, name):
    cur.execute("SELECT id FROM venues WHERE name = %s", (name,))
    rows = cur.fetchmany(2)
    if len(rows) > 1:
        raise ValueError("Found more than 1 venue with name {}".format(name))
    elif len(rows) == 0:
        raise ValueError("Didn't find venue with name {}".format(name))
    else:
        return rows[0][0]


def parse_date_time(date, time):
    local = datetime.datetime.strptime(
        "2019 {} {}".format(date, time), "%Y %d %b %H:%M"
    )
    local = pytz.timezone("Europe/London").localize(local)
    return local.astimezone(pytz.utc)


def import_from_iter(cur, user_id, it):
    reader = csv.reader(it, delimiter="\t")
    headings = tuple(next(reader))
    want_headings = (
        "Title",
        "Category",
        "Venue",
        "Duration",
        "Times",
        "Dates",
        "Book Tickets",
        "Group Name",
    )
    if headings != want_headings:
        raise ValueError(
            "Wrong CSV headings; got {}, want {}".format(headings, want_headings)
        )

    for row in reader:
        (
            title,
            category,
            venue_name,
            duration,
            times_str,
            dates_str,
            edfringe_url,
            _group_name,
        ) = row
        venue_id = lookup_venue_id(cur, venue_name)

        times = times_str.split(", ")
        dates = dates_str.split(", ")

        # Trust existing data, as updates are more likely to be bogus than existing imported data.
        cur.execute(
            "INSERT INTO shows (edfringe_url, title, category, venue_id, duration) "
            + "VALUES (%(edfringe_url)s, %(title)s, %(category)s, %(venue_id)s, %(duration)s) "
            + "ON CONFLICT ON CONSTRAINT shows_edfringe_url_key DO UPDATE SET edfringe_url = EXCLUDED.edfringe_url "
            + "RETURNING id",
            dict(
                edfringe_url=edfringe_url,
                category=category,
                title=title,
                venue_id=venue_id,
                duration=parse_time(duration),
            ),
        )
        show_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO interests (show_id, user_id, interest) VALUES (%s, %s, %s) "
            + "ON CONFLICT ON CONSTRAINT interests_show_id_user_id_key DO NOTHING",
            (show_id, user_id, "Like"),
        )

        for date in dates:
            for time in times:
                cur.execute(
                    "INSERT INTO performances (show_id, datetime_utc) VALUES (%s, %s) "
                    + "ON CONFLICT ON CONSTRAINT performances_show_id_datetime_utc_key DO NOTHING",
                    (show_id, parse_date_time(date, time)),
                )


def import_from_url(cur, user_id, url):
    req = requests.get(url)
    req.encoding = "utf_16"
    it = req.iter_lines(decode_unicode=True)
    return import_from_iter(cur, user_id, it)


def main(cur, user_id, path_or_url):
    if path_or_url.startswith("http"):
        return import_from_url(cur, user_id, path_or_url)
    else:
        with open(path_or_url, encoding="utf_16") as it:
            return import_from_iter(cur, user_id, it)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: {} email path/to/csv".format(sys.argv[0]), file=sys.stderr)
        sys.exit(1)
    config = Config.from_env()
    email, path_or_url = sys.argv[1:]
    with cursor(config) as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if row is None:
            print("Email address not found", file=sys.stderr)
        user_id = row[0]
        main(cur, user_id, path_or_url)
