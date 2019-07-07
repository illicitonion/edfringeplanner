import csv
import datetime
import sys
import time

import psycopg2
import pytz
import requests

from config import Config
from db import cursor
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


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

        if dates:
            some_date = "{:02d}-08-2019".format(int(dates[0].split(" ")[0]))
            for datetime_utc, available_or_sold_out in lookup_shows(
                edfringe_url, some_date
            ):
                cur.execute(
                    "INSERT INTO performances (show_id, datetime_utc) VALUES (%s, %s) "
                    + "ON CONFLICT ON CONSTRAINT performances_show_id_datetime_utc_key DO NOTHING "
                    + "RETURNING id",
                    (show_id, datetime_utc),
                )
                performance_id = cur.fetchone()[0]
                if available_or_sold_out == "sold_out":
                    cur.execute(
                        "INSERT INTO sold_out (performance_id) VALUES (%s) "
                        + "ON CONFLICT ON CONSTRAINT sold_out_performance_id_key DO NOTHING",
                        (performance_id,),
                    )


def wait_for(fn):
    condition = False
    count = 0
    while not condition:
        val, condition = fn()
        count += 1
        if count > 500:
            raise ValueError("Condition didn't become true")
        time.sleep(0.05)
    return val


def lookup_shows(edfringe_url, some_date_dd_mm_yyyy):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    try:
        url = "https://tickets.edfringe.com{}?step=times&day={}".format(
            edfringe_url, some_date_dd_mm_yyyy
        )
        driver.get(url)

        def find_dates():
            day_links = driver.find_elements_by_css_selector(
                ".event-dates:first-of-type a.date"
            )
            return day_links, day_links

        day_links = wait_for(find_dates)
        days = [(link.text, link.get_property("href")) for link in day_links]
        for day, href in days:
            driver.get(href)

            def find_links():
                links = driver.find_elements_by_css_selector(
                    ".times-panel:first-of-type a"
                )
                return links, links and all(link.text for link in links)

            links = wait_for(find_links)
            for link in links:
                time_str = link.text
                soldout = "tickets-soldout" in link.get_attribute("class").split(" ")
                local = datetime.datetime.strptime(
                    "2019 08 {:02d} {}".format(int(day), time_str), "%Y %m %d %H:%M"
                )
                local = pytz.timezone("Europe/London").localize(local)
                yield (
                    local.astimezone(pytz.utc),
                    "sold_out" if soldout else "available",
                )
    finally:
        driver.quit()


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
