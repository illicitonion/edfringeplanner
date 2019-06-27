from db import cursor


def share(config, *, shared_by, shared_with_email):
    with cursor(config) as cur:
        cur.execute(
            "INSERT INTO shares (shared_by, shared_with_email) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (shared_by, shared_with_email),
        )


def unshare(config, *, shared_by, shared_with_email):
    with cursor(config) as cur:
        cur.execute(
            "DELETE FROM shares WHERE shared_by = %s AND shared_with_email = %s",
            (shared_by, shared_with_email),
        )


def get_share_emails(config, user_id):
    with cursor(config) as cur:
        cur.execute(
            "SELECT shared_with_email FROM shares WHERE shared_by = %s ORDER BY shared_with_email ASC",
            (user_id,),
        )
        return [row[0] for row in cur.fetchall()]
