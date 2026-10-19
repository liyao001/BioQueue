import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from BioQueue.cli import _web_command, conf_get, prepare_install, read_conf, update_ini

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SAMPLE_CONF = """\
[env]
workspace =
log =
cpu = 2

[ml]
trainstore =
# predict = linear

[cluster]
type =
# stage_in = 0
"""


class UpdateIniTests(unittest.TestCase):
    def test_sets_empty_keys_and_keeps_comments(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        path = os.path.join(directory, "custom.conf")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE_CONF)
        update_ini(path, {"env": {"workspace": "/data/bq", "database": "/data/bq/db.sqlite3"}})
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("workspace = /data/bq", text)
        self.assertIn("database = /data/bq/db.sqlite3", text)
        self.assertIn("cpu = 2", text)
        self.assertIn("# predict = linear", text)
        self.assertIn("# stage_in = 0", text)
        parser = read_conf(path)
        self.assertEqual(conf_get(parser, "cluster", "type"), "")


class PrepareInstallTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        os.makedirs(os.path.join(self.root, "config"))
        os.makedirs(os.path.join(self.root, "BioQueue"))
        with open(os.path.join(self.root, "config", "custom.conf"), "w", encoding="utf-8") as handle:
            handle.write(SAMPLE_CONF)
        example = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "settings-example.py",
        )
        package = os.path.join(self.root, "BioQueue")
        shutil.copyfile(example, os.path.join(package, "settings-example.py"))
        with open(os.path.join(package, "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write("")
        self.data = os.path.join(self.root, "data")
        self.config_path = os.path.join(self.root, "config", "custom.conf")

    def _prepare(self, data=None, **kwargs):
        return prepare_install(data or self.data, config_path=self.config_path, **kwargs)

    def test_first_install_uses_sqlite_and_keeps_existing_cpu(self):
        info = self._prepare()
        self.assertFalse(info["created_settings"])
        self.assertTrue(os.path.isdir(os.path.join(self.data, "logs")))
        parser = read_conf(self.config_path)
        self.assertEqual(conf_get(parser, "env", "workspace"), os.path.abspath(self.data))
        self.assertEqual(conf_get(parser, "env", "cpu"), "2")
        self.assertTrue(conf_get(parser, "env", "secret_key"))
        self.assertEqual(conf_get(parser, "env", "feedback"), "no")
        with open(self.config_path, encoding="utf-8") as handle:
            self.assertIn("# stage_in = 0", handle.read())

        os.environ["BIOQUEUE_CUSTOM_CONF"] = self.config_path
        self.addCleanup(os.environ.pop, "BIOQUEUE_CUSTOM_CONF", None)
        import BioQueue.default_settings as settings

        importlib.reload(settings)
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(
            settings.DATABASES["default"]["NAME"],
            os.path.join(os.path.abspath(self.data), "db.sqlite3"),
        )
        self.assertEqual(settings.SECRET_KEY, conf_get(parser, "env", "secret_key"))
        self.assertFalse(settings.DEBUG)
        self.assertEqual(settings.ALLOWED_HOSTS, ["localhost", "127.0.0.1", "[::1]"])

    def test_database_env_selects_postgres(self):
        self._prepare()
        os.environ["BIOQUEUE_CUSTOM_CONF"] = self.config_path
        os.environ["BIOQUEUE_DB_ENGINE"] = "django.db.backends.postgresql"
        os.environ["BIOQUEUE_DB_NAME"] = "bioqueue"
        os.environ["BIOQUEUE_DB_USER"] = "bioqueue"
        os.environ["BIOQUEUE_DB_PASSWORD"] = "secret"
        os.environ["BIOQUEUE_DB_HOST"] = "db.example"
        os.environ["BIOQUEUE_DB_PORT"] = "5432"
        for key in (
            "BIOQUEUE_CUSTOM_CONF",
            "BIOQUEUE_DB_ENGINE",
            "BIOQUEUE_DB_NAME",
            "BIOQUEUE_DB_USER",
            "BIOQUEUE_DB_PASSWORD",
            "BIOQUEUE_DB_HOST",
            "BIOQUEUE_DB_PORT",
        ):
            self.addCleanup(os.environ.pop, key, None)
        import BioQueue.default_settings as settings

        importlib.reload(settings)
        db = settings.DATABASES["default"]
        self.assertEqual(db["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(db["NAME"], "bioqueue")
        self.assertEqual(db["USER"], "bioqueue")
        self.assertEqual(db["HOST"], "db.example")
        self.assertEqual(db["PORT"], "5432")

    def test_debug_and_hosts_follow_env_then_config(self):
        self._prepare()
        update_ini(
            self.config_path,
            {"env": {"debug": "yes", "allowed_hosts": "lab.example, 127.0.0.1"}},
        )
        os.environ["BIOQUEUE_CUSTOM_CONF"] = self.config_path
        self.addCleanup(os.environ.pop, "BIOQUEUE_CUSTOM_CONF", None)
        import BioQueue.default_settings as settings

        importlib.reload(settings)
        self.assertTrue(settings.DEBUG)
        self.assertEqual(settings.ALLOWED_HOSTS, ["lab.example", "127.0.0.1"])

        os.environ["BIOQUEUE_DEBUG"] = "0"
        os.environ["BIOQUEUE_ALLOWED_HOSTS"] = "other.example"
        os.environ["BIOQUEUE_BIND_HOST"] = "0.0.0.0"
        for key in ("BIOQUEUE_DEBUG", "BIOQUEUE_ALLOWED_HOSTS", "BIOQUEUE_BIND_HOST"):
            self.addCleanup(os.environ.pop, key, None)
        importlib.reload(settings)
        self.assertFalse(settings.DEBUG)
        self.assertEqual(settings.ALLOWED_HOSTS, ["other.example"])

        os.environ.pop("BIOQUEUE_ALLOWED_HOSTS")
        os.environ["BIOQUEUE_BIND_HOST"] = "bench.local"
        importlib.reload(settings)
        self.assertEqual(settings.ALLOWED_HOSTS, ["lab.example", "127.0.0.1", "bench.local"])

    def test_missing_secret_is_rejected(self):
        bare = os.path.join(self.root, "bare.conf")
        with open(bare, "w", encoding="utf-8") as handle:
            handle.write("[env]\nworkspace = /tmp/bq\nsecret_key =\n")
        os.environ["BIOQUEUE_CUSTOM_CONF"] = bare
        os.environ.pop("BIOQUEUE_SECRET_KEY", None)
        self.addCleanup(os.environ.pop, "BIOQUEUE_CUSTOM_CONF", None)
        import BioQueue.default_settings as settings
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            importlib.reload(settings)
        os.environ["BIOQUEUE_CUSTOM_CONF"] = self.config_path
        self._prepare()
        importlib.reload(settings)

    def test_second_install_does_not_rotate_secret_or_move_data(self):
        self._prepare()
        parser = read_conf(self.config_path)
        secret = conf_get(parser, "env", "secret_key")
        again = self._prepare()
        self.assertFalse(again["created_settings"])
        parser = read_conf(self.config_path)
        self.assertEqual(conf_get(parser, "env", "secret_key"), secret)
        with self.assertRaises(SystemExit):
            self._prepare(os.path.join(self.root, "elsewhere"))

    def test_force_moves_the_data_folder(self):
        self._prepare()
        moved = os.path.join(self.root, "elsewhere")
        self._prepare(moved, force_data=True)
        parser = read_conf(self.config_path)
        self.assertEqual(conf_get(parser, "env", "workspace"), os.path.abspath(moved))
        self.assertEqual(conf_get(parser, "env", "log"), os.path.join(os.path.abspath(moved), "logs"))


class WebCommandTests(unittest.TestCase):
    def test_runserver_is_a_module_the_reloader_can_reexec(self):
        argv = _web_command("127.0.0.1:8000")
        self.assertEqual(argv[1:5], ["-m", "BioQueue.serve", "runserver", "--insecure"])
        self.assertNotIn("-c", argv)

        proc = subprocess.run(
            [sys.executable, "-m", "BioQueue.serve", "--reloader-args"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        child = proc.stdout.splitlines()
        self.assertIn("-m", child)
        self.assertIn("BioQueue.serve", child)
        self.assertNotIn("-c", child)


if __name__ == "__main__":
    unittest.main()
