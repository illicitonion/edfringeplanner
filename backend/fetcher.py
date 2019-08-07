import datetime
import time
from contextlib import contextmanager

import pytz
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def check_soldout_for_single_time(cur, show_id):
    cur.execute("SELECT edfringe_url FROM shows WHERE id = %s", (show_id,))
    edfringe_url = cur.fetchone()[0]

    with make_driver() as driver:
        day_links = lookup_day_links(driver, edfringe_url, "01-08-2019")
        for day_link in day_links:
            day = day_link.text
            span = day_link.find_element_by_tag_name("span")
            soldout = "tickets-soldout" in span.get_attribute("class").split(" ")
            if soldout:
                cur.execute(
                    "SELECT id FROM performances WHERE show_id = %s AND datetime_utc > %s LIMIT 1",
                    (
                        show_id,
                        datetime.datetime.strptime(
                            "2019 08 {:02d} 05:00 +0100".format(int(day)),
                            "%Y %m %d %H:%M %z",
                        ),
                    ),
                )
                performance_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO sold_out (performance_id) VALUES (%s) "
                    + "ON CONFLICT ON CONSTRAINT sold_out_performance_id_key DO NOTHING",
                    (performance_id,),
                )


def fetch_multitime(cur, show_id, some_date_DD_MM_YYYY):
    cur.execute("SELECT edfringe_url FROM shows WHERE id = %s", (show_id,))
    edfringe_url = cur.fetchone()[0]

    for datetime_utc, available_or_sold_out in lookup_shows(
        edfringe_url, some_date_DD_MM_YYYY
    ):
        cur.execute(
            "INSERT INTO performances (show_id, datetime_utc) VALUES (%(show_id)s, %(datetime_utc)s) "
            + "ON CONFLICT ON CONSTRAINT performances_show_id_datetime_utc_key "
            + "DO UPDATE SET show_id = EXCLUDED.show_id "
            + "RETURNING id",
            dict(show_id=show_id, datetime_utc=datetime_utc),
        )
        performance_id = cur.fetchone()[0]
        if available_or_sold_out == "sold_out":
            cur.execute(
                "INSERT INTO sold_out (performance_id) VALUES (%s) "
                + "ON CONFLICT ON CONSTRAINT sold_out_performance_id_key DO NOTHING",
                (performance_id,),
            )


@contextmanager
def make_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    try:
        yield driver
    finally:
        driver.quit()


def lookup_shows(edfringe_url, some_date_dd_mm_yyyy):
    with make_driver() as driver:
        day_links = lookup_day_links(driver, edfringe_url, some_date_dd_mm_yyyy)
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


def lookup_day_links(driver, edfringe_url, some_date_dd_mm_yyyy):
    url = "https://tickets.edfringe.com{}?step=times&day={}".format(
        edfringe_url, some_date_dd_mm_yyyy
    )
    driver.get(url)

    def find_dates():
        day_links = driver.find_elements_by_css_selector(
            ".event-dates:first-of-type a.date"
        )
        return day_links, day_links

    try:
        day_links = wait_for(find_dates)
    except ValueError:
        print("Found no day links for show {}".format(edfringe_url))
        return []
    return day_links


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
