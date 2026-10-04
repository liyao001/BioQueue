import importlib
import os
import shutil
import tempfile
import unittest

from BioQueue.cli import conf_get, prepare_install, read_conf, update_ini


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


if __name__ == "__main__":
    unittest.main()
