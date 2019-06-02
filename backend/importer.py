import csv
import datetime
import sys

import psycopg2
import pytz

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


def main(path):
    with open(path, encoding="utf_16") as f:
        reader = csv.reader(f, delimiter="\t")
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

        with cursor() as cur:
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

                # Upsert trusts that our data source isn't malicious.
                cur.execute(
                    "INSERT INTO shows (edfringe_url, title, category, venue_id, duration) "
                    + "VALUES (%(edfringe_url)s, %(title)s, %(category)s, %(venue_id)s, %(duration)s) "
                    + "ON CONFLICT ON CONSTRAINT shows_edfringe_url_key DO "
                    + "UPDATE SET "
                    + "title = %(title)s,"
                    + "category = %(category)s,"
                    + "venue_id = %(venue_id)s, "
                    + "duration = %(duration)s "
                    + "WHERE shows.edfringe_url = %(edfringe_url)s "
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

                for date in dates:
                    for time in times:
                        cur.execute(
                            "INSERT INTO performances (show_id, datetime_utc) VALUES (%s, %s) "
                            + "ON CONFLICT ON CONSTRAINT performances_show_id_datetime_utc_key DO NOTHING",
                            (show_id, parse_date_time(date, time)),
                        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: {} path/to/csv".format(sys.argv[0]), file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
