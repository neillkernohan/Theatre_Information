"""Cross-app notification support (shared email sending and the EmailLog model).

This is a plain support package, not a Flask blueprint — it has no views or
routes. The auditions and proxy apps build their own HTML (from their own
templates) and hand it to ``notifications.core.send_logged_email`` to send and
audit-log in one place.
"""
