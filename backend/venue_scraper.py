from selenium import webdriver

from db import cursor


def get_venues():
    driver = webdriver.Chrome()
    try:
        driver.get("https://tickets.edfringe.com/venues")

        while True:
            venues_container = driver.find_element_by_class_name("venues")
            for venue in venues_container.find_elements_by_class_name("venue-details"):
                name = venue.find_element_by_tag_name("h3").text
                lis = venue.find_elements_by_tag_name("li")
                address = lis[0].text
                number_text = lis[1].text.split()[-1]
                lat = lis[3].get_attribute("data-lat")
                long = lis[3].get_attribute("data-lng")
                yield (int(number_text), name, address, (float(lat), float(long)))
            next_links = driver.find_elements_by_link_text("Next »")
            if not next_links:
                break
            next_links[0].click()
    finally:
        driver.quit()


venues = tuple(get_venues())


with cursor() as cur:
    for venue in sorted(venues):
        print(
            cur.mogrify(
                "INSERT INTO venues (edfringe_number, name, address, latlong) VALUES (%s, %s, %s, POINT%s)",
                venue,
            ).decode("utf-8"),
            end=";\n",
        )
