import configparser
import os

_DEFAULTS = {
    "max_commits": 20,
    "server_cache_ttl": 3600,
}


def _find_covtest_ini(folder):
    """Search for covtest.ini starting from *folder*.

    Search order:
    1. <folder>/covtest.ini
    2. <folder>/test/covtest.ini
    3. <folder>/tests/covtest.ini
    4. Walk upward through parent directories, checking each for covtest.ini
    """
    folder = os.path.realpath(folder)

    candidates = [
        os.path.join(folder, "covtest.ini"),
        os.path.join(folder, "test", "covtest.ini"),
        os.path.join(folder, "tests", "covtest.ini"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    parent = os.path.dirname(folder)
    while parent != folder:
        path = os.path.join(parent, "covtest.ini")
        if os.path.isfile(path):
            return path
        folder, parent = parent, os.path.dirname(parent)

    return None


def read_config(folder):
    """Return the [covtest] section merged with defaults, with typed values."""
    ini_path = _find_covtest_ini(folder)
    raw = {}
    if ini_path is not None:
        parser = configparser.ConfigParser()
        parser.read(ini_path)
        if parser.has_section("covtest"):
            raw = dict(parser["covtest"])

    result = dict(_DEFAULTS)
    result.update(raw)
    result["max_commits"] = int(result["max_commits"])
    result["server_cache_ttl"] = int(result["server_cache_ttl"])
    return result


def read_server_url(folder):
    return read_config(folder).get("server_url")
