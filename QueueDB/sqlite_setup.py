"""SQLite settings for the web app and the worker sharing one database file."""


def apply_sqlite_concurrency_pragmas(cursor):
    """Let one process read while the other writes, and wait instead of failing.

    The default rollback journal locks the whole file for every write, so the
    site and the worker raise "database is locked" against each other. WAL keeps
    readers out of that lock. busy_timeout is milliseconds.
    """
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=30000;")


def configure_sqlite_connection(connection):
    if getattr(connection, "vendor", None) != "sqlite":
        return
    name = str(connection.settings_dict.get("NAME") or "")
    if not name or name == ":memory:" or name.startswith("file::memory:"):
        return
    cursor = connection.cursor()
    try:
        apply_sqlite_concurrency_pragmas(cursor)
    finally:
        cursor.close()
