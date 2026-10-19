"""Keep developer secrets and unpublished migrations out of the wheel."""
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

# A checkout can contain extra QueueDB migrations that are not part of the
# published history (and some of them are PostgreSQL-only). Shipping them
# makes `migrate` fail on a fresh SQLite install.
_PUBLIC_MIGRATIONS = {
    "__init__",
    "0001_initial",
    "0050_protocollist_template_job_sample_sheet",
    "0051_notificationhook",
    "0052_virtualenvironment_recipe",
    "0053_sync_models",
}


class build_py(_build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if package == "BioQueue":
            return [item for item in modules if item[1] != "settings"]
        if package == "QueueDB.migrations":
            return [item for item in modules if item[1] in _PUBLIC_MIGRATIONS]
        return modules


setup(cmdclass={"build_py": build_py})
