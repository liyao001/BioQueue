import os
import shutil
import sqlite3
import tempfile
import unittest

from QueueDB.sqlite_setup import apply_sqlite_concurrency_pragmas, configure_sqlite_connection


class SqliteSetupTests(unittest.TestCase):
    def test_file_database_uses_wal_and_waits(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        path = os.path.join(directory, "db.sqlite3")
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        cursor = connection.cursor()
        apply_sqlite_concurrency_pragmas(cursor)
        self.assertEqual(cursor.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(cursor.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

    def test_memory_database_is_left_alone(self):
        class MemoryConnection(object):
            vendor = "sqlite"
            settings_dict = {"NAME": ":memory:"}

            def cursor(self):
                raise AssertionError("in-memory databases used by tests should not be reconfigured")

        configure_sqlite_connection(MemoryConnection())


if __name__ == "__main__":
    unittest.main()
