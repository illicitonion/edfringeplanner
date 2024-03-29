from __future__ import annotations

import dataclasses
import datetime
from collections import defaultdict
from dataclasses import dataclass
from sortedcontainers import SortedSet
from typing import FrozenSet, List, Optional

import pytz

from db import cursor
from sharing import get_shared_by_user_ids_and_emails


@dataclass(eq=True, frozen=True)
class Venue:
    name: str
    google_maps_url: str


@dataclass(eq=True, frozen=True)
class Event:
    show_id: int
    title: str
    category: str
    venue: Venue
    duration: datetime.timedelta
    start_edinburgh: datetime.datetime
    edfringe_url: str
    show_interest: str
    performance_id: int
    performance_interest: str
    user_id: int
    user_email: Optional[str]
    shared_interests: FrozenSet[Event]
    last_chance: bool = False

    @property
    def title_maybe_truncated(self):
        limit = 50
        if len(self.title) > limit:
            return self.title[: limit - 1] + "…"
        return self.title

    @property
    def booked(self):
        return self.performance_interest == "Booked"

    @property
    def interest(self):
        if self.performance_interest == "Booked" or self.show_interest == "Booked":
            return "Booked"
        if self.performance_interest == "Must" or self.show_interest == "Must":
            return "Must"
        if self.performance_interest == "Like" or self.show_interest == "Like":
            return "Like"
        if self.performance_interest:
            return self.performance_interest
        return self.show_interest

    @property
    def css_class(self):
        if self.booked:
            return "booked"
        elif self.interest == "Must":
            if self.last_chance:
                return "lastchance"
            return "important0"
        elif self.interest == "Like":
            return "important1"
        else:
            return "important2"

    def interest_int(self, shared_boost):
        if self.booked:
            return 99999
        if self.interest == "Booked":
            return 0

        bonus = 0

        if self.shared_interests:
            if shared_boost == "bit":
                base_bonus = 200
            elif shared_boost == "lot":
                base_bonus = 800
            else:
                base_bonus = 0
            for shared_interest in self.shared_interests:
                if shared_interest.booked:
                    multiplier = 4
                elif shared_interest.interest == "Must":
                    multiplier = 2
                else:
                    multiplier = 1
                bonus += base_bonus * multiplier

        if self.interest == "Must":
            if self.last_chance:
                return 10000 + bonus
            return 1000 + bonus
        elif self.interest == "Like":
            if self.last_chance:
                return 200 + bonus
            return 100 + bonus
        else:
            return 1 + bonus

    @property
    def max_shared_interest(self):
        if not self.shared_interests:
            return ""
        if any(event.booked for event in self.shared_interests):
            return "Booked"
        return max(
            "" if event.interest == "Booked" else event.interest
            for event in self.shared_interests
        )

    def intersects(self, other: Event) -> bool:
        if self.start_edinburgh <= other.start_edinburgh:
            return self.start_edinburgh + self.duration > other.start_edinburgh
        else:
            return self.start_edinburgh < other.start_edinburgh + other.duration


@dataclass
class EventOrPadding:
    event: Event
    one_minute_chunks: int


@dataclass
class Column:
    header: str
    events_or_padding: List[EventOrPadding]


def duration_to_chunks(duration: datetime.timedelta):
    return duration.total_seconds() / 60


def bin_pack_events(events, shared_boost):
    if not events:
        return [], 5, 0

    categories_to_columns = defaultdict(list)

    def category(event: Event) -> str:
        if event.booked:
            return "Booked"
        else:
            return event.category

    def importance(event_or_padding: EventOrPadding) -> int:
        event = event_or_padding.event
        if event is None:
            return 0
        else:
            return event.interest_int(shared_boost)

    start_of_day = min(event.start_edinburgh for event in events).replace(
        minute=0, second=0
    )
    end_of_day = max(
        event.start_edinburgh + event.duration for event in events
    ).replace(minute=0, second=0) + datetime.timedelta(hours=1)
    number_of_hours = int((end_of_day - start_of_day).total_seconds()) // 3600

    for event in events:
        columns = categories_to_columns[category(event)]
        for column in columns:
            last_event = column[-1].event
            last_event_end = last_event.start_edinburgh + last_event.duration
            if last_event_end < event.start_edinburgh:
                if last_event_end < event.start_edinburgh:
                    column.append(
                        EventOrPadding(
                            None,
                            duration_to_chunks(event.start_edinburgh - last_event_end),
                        )
                    )
                column.append(EventOrPadding(event, duration_to_chunks(event.duration)))
                break
        else:
            new_column = [
                EventOrPadding(
                    None, duration_to_chunks(event.start_edinburgh - start_of_day)
                ),
                EventOrPadding(event, duration_to_chunks(event.duration)),
            ]
            columns.append(new_column)
    for columns in categories_to_columns.values():
        for column in columns:
            last_event = column[-1].event
            last_event_end = last_event.start_edinburgh + last_event.duration
            if last_event_end < end_of_day:
                column.append(
                    EventOrPadding(
                        None, duration_to_chunks(end_of_day - last_event_end)
                    )
                )

    columns = []
    for category, category_columns in categories_to_columns.items():
        for column in category_columns:
            columns.append(Column(header=category, events_or_padding=column))
    columns.sort(
        key=lambda c: sum(importance(event) for event in c.events_or_padding),
        reverse=True,
    )
    return columns, start_of_day.hour, number_of_hours


def load_events(config, user_id, date, filter: Filter, hydrate_shares, email=None):
    # TODO: Don't hard-code time zones
    start_of_day = datetime.datetime.strptime(
        "{} 05:00:00 +0100".format(date), "%Y-%m-%d %H:%M:%S %z"
    )
    end_of_day = datetime.datetime.strptime(
        "{} 05:00:00 +0100".format(date + datetime.timedelta(days=1)),
        "%Y-%m-%d %H:%M:%S %z",
    )

    shared_interests = defaultdict(set)
    if hydrate_shares:
        for (
            shared_by_user_id,
            shared_by_user_email,
        ) in get_shared_by_user_ids_and_emails(config, user_id):
            events = load_events(
                config,
                shared_by_user_id,
                date,
                Filter.show_all(),
                False,
                email=shared_by_user_email,
            )
            for event in events:
                shared_interests[event.performance_id].add(event)

    events = []
    booked_events = []
    later_event_ids = set()
    with cursor(config) as cur:
        # TODO: Filter on start/end time?
        cur.execute(
            "SELECT shows.id, shows.title, shows.category, shows.duration, shows.edfringe_url, performances.datetime_utc, venues.name, venues.latlong, interests.interest, performances.id, user_performance_interests.interest, sold_out.id "
            + "FROM shows INNER JOIN performances ON shows.id = performances.show_id "
            + "INNER JOIN venues ON shows.venue_id = venues.id "
            + "INNER JOIN interests ON shows.id = interests.show_id "
            + "INNER JOIN users ON users.id = interests.user_id "
            + "LEFT JOIN (SELECT * FROM performance_interests WHERE user_id = %(user_id)s) user_performance_interests ON performances.id = user_performance_interests.performance_id "
            + "LEFT JOIN sold_out ON sold_out.performance_id = performances.id "
            + "WHERE users.id = %(user_id)s "
            + "AND performances.datetime_utc > users.start_datetime_utc AND performances.datetime_utc < users.end_datetime_utc "
            + "ORDER BY performances.datetime_utc ASC, shows.title ASC",
            {"user_id": user_id},
        )
        rows = cur.fetchall()
        for row in rows:
            # TODO: Shows which overlap around the day change
            (
                show_id,
                title,
                category,
                duration,
                edfringe_url,
                datetime_utc,
                venue_name,
                venue_latlong,
                show_interest,
                performance_id,
                performance_interest,
                sold_out_id,
            ) = row
            start_edinburgh = datetime_utc.astimezone(pytz.timezone("Europe/London"))
            end_edinburgh = start_edinburgh + duration
            if end_edinburgh <= start_of_day:
                continue
            if start_edinburgh >= end_of_day:
                # TODO: Filter out future conflicts
                later_event_ids.add(show_id)
                continue
            event = Event(
                show_id=show_id,
                title=title,
                category=category,
                venue=Venue(
                    name=venue_name,
                    google_maps_url="https://www.google.co.uk/maps/search/{}".format(
                        venue_latlong
                    ),
                ),
                edfringe_url=edfringe_url,
                duration=duration,
                start_edinburgh=start_edinburgh,
                show_interest=show_interest,
                performance_id=performance_id,
                performance_interest=performance_interest,
                user_id=user_id,
                shared_interests=frozenset(shared_interests[performance_id]),
                user_email=email,
            )
            if event.booked:
                booked_events.append(event)
            else:
                if sold_out_id is not None:
                    continue
            events.append(event)

    def maybe_last_chance(event):
        return (
            event
            if event.show_id in later_event_ids
            else dataclasses.replace(event, last_chance=True)
        )

    events = [
        maybe_last_chance(event)
        for event in events
        if filter.show(event)
        and (
            event.booked
            or not any(event.intersects(booked_event) for booked_event in booked_events)
        )
    ]
    return events


def set_interest(config, user_id, show_id, interest):
    with cursor(config) as cur:
        cur.execute(
            "INSERT INTO interests (show_id, user_id, interest) VALUES (%(show_id)s, %(user_id)s, %(interest)s) "
            + "ON CONFLICT ON CONSTRAINT interests_show_id_user_id_key DO "
            + "UPDATE SET interest = %(interest)s where interests.show_id = %(show_id)s and interests.user_id = %(user_id)s",
            dict(show_id=show_id, user_id=user_id, interest=interest),
        )


def remove_interest(config, user_id, show_id):
    with cursor(config) as cur:
        cur.execute(
            "DELETE FROM interests WHERE user_id = %s AND show_id = %s",
            (user_id, show_id),
        )
        cur.execute(
            "DELETE FROM performance_interests WHERE user_id = %s AND show_id = %s",
            (user_id, show_id),
        )


def mark_booked(config, user_id, performance_id):
    set_performance_interest(config, user_id, performance_id, interest="Booked")
    with cursor(config) as cur:
        cur.execute("SELECT show_id FROM performances WHERE id = %s", (performance_id,))
        show_id = cur.fetchone()[0]
    set_interest(config, user_id, show_id, "Booked")


def set_performance_interest(config, user_id, performance_id, interest):
    with cursor(config) as cur:
        cur.execute("SELECT show_id FROM performances WHERE id = %s", (performance_id,))
        show_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO performance_interests (show_id, performance_id, user_id, interest) "
            + "VALUES (%(show_id)s, %(performance_id)s, %(user_id)s, %(interest)s) "
            + "ON CONFLICT ON CONSTRAINT performance_interests_performance_id_user_id_key DO "
            + "UPDATE SET interest = %(interest)s WHERE performance_interests.user_id = %(user_id)s AND performance_interests.performance_id = %(performance_id)s",
            dict(
                show_id=show_id,
                performance_id=performance_id,
                user_id=user_id,
                interest=interest,
            ),
        )


def unset_performance_interest(config, user_id, *, show_id=None, performance_id=None):
    with cursor(config) as cur:
        if show_id is not None:
            cur.execute(
                "DELETE FROM performance_interests WHERE user_id = %s AND show_id = %s",
                (user_id, show_id),
            )
        elif performance_id is not None:
            cur.execute(
                "DELETE FROM performance_interests WHERE user_id = %s AND performance_id = %s",
                (user_id, performance_id),
            )


@dataclass(frozen=True)
class Filter:
    show_like: bool
    show_must: bool
    show_booked: bool
    start_at: Optional[datetime.datetime]
    end_at: Optional[datetime.datetime]
    show_past: bool
    hidden_categories: SortedSet[str]

    @staticmethod
    def show_all() -> Filter:
        return Filter(
            show_like=True,
            show_must=True,
            show_booked=True,
            start_at=None,
            end_at=None,
            show_past=True,
            hidden_categories=SortedSet(),
        )

    def show(self, event: Event):
        now = datetime.datetime.utcnow().astimezone(pytz.timezone("Europe/London"))
        if not self.show_past and event.start_edinburgh <= now:
            return False
        if self.start_at is not None:
            if self.start_at > event.start_edinburgh:
                return False
        if self.end_at is not None:
            if self.end_at < event.start_edinburgh:
                return False
        if event.booked or event.last_chance:
            return True
        if event.interest == "Like" and not self.show_like:
            return False
        if event.interest == "Must" and not self.show_must:
            return False
        if event.interest == "Booked" and not self.show_booked:
            return False
        if event.category in self.hidden_categories:
            return False
        return True


_interest_rates = {"": 0, None: 0, "Booked": 0, "Like": 1, "Must": 2}


def interest_comparator(interest):
    return _interest_rates.get(interest, 0)
