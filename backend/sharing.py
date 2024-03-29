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


def get_shared_by_user_ids_and_emails(config, user_id):
    with cursor(config) as cur:
        cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Couldn't find email address for user {}".format(user_id))
        user_email = row[0]

        cur.execute(
            "SELECT users.id, users.email FROM users INNER JOIN shares ON users.id = shares.shared_by WHERE shares.shared_with_email = %s ORDER BY users.email ASC",
            (user_email,),
        )

        return [(row[0], row[1]) for row in cur.fetchall()]


def get_share_emails(config, user_id):
    with cursor(config) as cur:
        cur.execute(
            "SELECT shared_with_email FROM shares WHERE shared_by = %s ORDER BY shared_with_email ASC",
            (user_id,),
        )

        shared_with_user = [row[0] for row in cur.fetchall()]

        shared_by_ids_and_emails = get_shared_by_user_ids_and_emails(config, user_id)

        shared_by_user = [email for id, email in shared_by_ids_and_emails]

        return shared_by_user, shared_with_user
