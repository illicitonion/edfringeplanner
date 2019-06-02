import functools
import os
from contextlib import contextmanager

import psycopg2


@functools.lru_cache(maxsize=1)
def name():
    return os.environ["EDFRINGEPLANNER_DB_NAME"]


@contextmanager
def cursor():
    with psycopg2.connect("dbname={}".format(name())) as conn:
        with conn.cursor() as cur:
            yield cur
