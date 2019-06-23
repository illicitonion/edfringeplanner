from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    database_name: str
    session_key: str
    mailgun_domain: str
    mailgun_key: str
    domain_prefix: str

    @classmethod
    def from_env(cls) -> Config:
        return Config(
            database_name=os.environ["EDFRINGEPLANNER_DB_NAME"],
            session_key=os.environ["EDFRINGEPLANNER_SESSION_KEY"],
            mailgun_domain=os.environ["EDFRINGEPLANNER_MAILGUN_DOMAIN"],
            mailgun_key=os.environ["EDFRINGEPLANNER_MAILGUN_KEY"],
            domain_prefix=os.environ["EDFRINGEPLANNER_DOMAIN_PREFIX"],
        )
