"""
Audience queries against the MySQL patron/ticket database.
Each function returns a list of dicts: {email, first_name, last_name}.
All queries exclude No_Email=1 and addresses in the Unsubscribed table.
"""
import mysql.connector
import os

_BASE_EXCLUSION = """
    AND p.No_Email = 0
    AND p.Email IS NOT NULL
    AND p.Email != ''
    AND LOWER(p.Email) NOT IN (
        SELECT LOWER(email) FROM Unsubscribed
    )
"""


def _connect():
    return mysql.connector.connect(
        host=os.getenv('MYSQL_HOST'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DATABASE'),
    )


def _fetch(query, params=None):
    db = _connect()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(query, params or ())
        return cur.fetchall()
    finally:
        db.close()


def audience_all_opted_in():
    return _fetch(f"""
        SELECT First_name AS first_name, Last_name AS last_name, Email AS email
        FROM Patrons p
        WHERE 1=1
        {_BASE_EXCLUSION}
        ORDER BY Last_name, First_name
    """)


def audience_ticket_buyers_2018():
    """Patrons who purchased tickets to at least one performance since Jan 1 2018."""
    return _fetch(f"""
        SELECT DISTINCT p.First_name AS first_name, p.Last_name AS last_name, p.Email AS email
        FROM Patrons p
        WHERE EXISTS (
            SELECT 1 FROM Ticket_Info t
            WHERE CONCAT(p.First_name, ' ', p.Last_name) = t.Customer
              AND t.Performance_date >= '2018-01-01'
              AND t.Transaction_type != 'Reserve'
        )
        {_BASE_EXCLUSION}
        ORDER BY p.Last_name, p.First_name
    """)


def audience_members():
    return _fetch(f"""
        SELECT First_name AS first_name, Last_name AS last_name, Email AS email
        FROM Patrons p
        WHERE p.is_member = 1
        {_BASE_EXCLUSION}
        ORDER BY Last_name, First_name
    """)


def audience_volunteers():
    return _fetch(f"""
        SELECT First_name AS first_name, Last_name AS last_name, Email AS email
        FROM Patrons p
        WHERE p.Marketing_Lists LIKE %s
        {_BASE_EXCLUSION}
        ORDER BY Last_name, First_name
    """, ('%Volunteers%',))


def audience_marketing_list(list_name):
    return _fetch(f"""
        SELECT First_name AS first_name, Last_name AS last_name, Email AS email
        FROM Patrons p
        WHERE p.Marketing_Lists LIKE %s
        {_BASE_EXCLUSION}
        ORDER BY Last_name, First_name
    """, (f'%{list_name}%',))


def audience_season_buyers(season):
    """Patrons who bought tickets in a specific season (YYYY-MM-DD format)."""
    return _fetch(f"""
        SELECT DISTINCT p.First_name AS first_name, p.Last_name AS last_name, p.Email AS email
        FROM Patrons p
        WHERE EXISTS (
            SELECT 1 FROM Ticket_Info t
            WHERE CONCAT(p.First_name, ' ', p.Last_name) = t.Customer
              AND DATE_FORMAT(t.Season, '%Y-%m-%d') = %s
              AND t.Transaction_type != 'Reserve'
        )
        {_BASE_EXCLUSION}
        ORDER BY p.Last_name, p.First_name
    """, (season,))


def get_available_seasons():
    db = _connect()
    try:
        cur = db.cursor()
        cur.execute("""
            SELECT DATE_FORMAT(Season, '%Y-%m-%d') AS s
            FROM Ticket_Info GROUP BY Season ORDER BY Season DESC
        """)
        return [row[0] for row in cur.fetchall()]
    finally:
        db.close()


def get_available_marketing_lists():
    db = _connect()
    try:
        cur = db.cursor()
        cur.execute("SELECT DISTINCT Marketing_Lists FROM Patrons WHERE Marketing_Lists IS NOT NULL AND Marketing_Lists != ''")
        all_lists = set()
        for (val,) in cur.fetchall():
            for item in val.split(','):
                item = item.strip()
                if item:
                    all_lists.add(item)
        return sorted(all_lists)
    finally:
        db.close()


AUDIENCE_HANDLERS = {
    'all_opted_in':       lambda p: audience_all_opted_in(),
    'ticket_buyers_2018': lambda p: audience_ticket_buyers_2018(),
    'members':            lambda p: audience_members(),
    'volunteers':         lambda p: audience_volunteers(),
    'marketing_list':     lambda p: audience_marketing_list(p.get('list_name', '')),
    'season_buyers':      lambda p: audience_season_buyers(p.get('season', '')),
}


def resolve_audience(audience_type, params=None):
    handler = AUDIENCE_HANDLERS.get(audience_type)
    if not handler:
        return []
    return handler(params or {})
