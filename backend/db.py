from contextlib import contextmanager

import psycopg2

from config import Config


@contextmanager
def cursor(config: Config):
    with psycopg2.connect("dbname={}".format(config.database_name)) as conn:
        with conn.cursor() as cur:
            yield cur
