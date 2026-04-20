import configparser
import os


def _find_covtest_ini(folder):
    """Search for covtest.ini starting from *folder*.

    Search order:
    1. <folder>/covtest.ini
    2. <folder>/test/covtest.ini
    3. <folder>/tests/covtest.ini
    4. Walk upward through parent directories, checking each for covtest.ini
    """
    folder = os.path.realpath(folder)

    # Check the given folder and common test subdirectories first
    candidates = [
        os.path.join(folder, "covtest.ini"),
        os.path.join(folder, "test", "covtest.ini"),
        os.path.join(folder, "tests", "covtest.ini"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    # Walk upward
    parent = os.path.dirname(folder)
    while parent != folder:
        path = os.path.join(parent, "covtest.ini")
        if os.path.isfile(path):
            return path
        folder, parent = parent, os.path.dirname(parent)

    return None


def read_config(folder):
    """Return the [covtest] section of the nearest covtest.ini as a dict,
    or an empty dict if no file is found."""
    ini_path = _find_covtest_ini(folder)
    if ini_path is None:
        return {}
    cfg = configparser.ConfigParser()
    cfg.read(ini_path)
    if cfg.has_section("covtest"):
        return dict(cfg["covtest"])
    return {}


def read_server_url(folder):
    return read_config(folder).get("server_url")
