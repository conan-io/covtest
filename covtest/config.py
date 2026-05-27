import configparser
import os

_DEFAULTS = {
    "max_commits": 20,
    "server_cache_ttl": 3600,
}

# Environment variable → config key mapping.
# Env vars take priority over covtest.ini values.
_ENV_MAP = {
    "COVTEST_URL": "server_url",
    "COVTEST_USER": "auth_user",
    "COVTEST_PASSWORD": "auth_password",
    "COVTEST_TOKEN": "auth_token",
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
    """Return the [covtest] section merged with defaults and env-var overrides.

    Priority (highest to lowest):
    1. Environment variables (COVTEST_URL, COVTEST_USER, COVTEST_PASSWORD, COVTEST_TOKEN)
    2. covtest.ini [covtest] section
    3. Built-in defaults

    Auth keys available in the returned dict:
      ``server_url``, ``auth_user``, ``auth_password``, ``auth_token``
    """
    ini_path = _find_covtest_ini(folder)
    raw = {}
    if ini_path is not None:
        parser = configparser.ConfigParser()
        parser.read(ini_path)
        if parser.has_section("covtest"):
            raw = dict(parser["covtest"])

    result = dict(_DEFAULTS)
    result.update(raw)

    # Environment variables override ini values
    for env_var, key in _ENV_MAP.items():
        val = os.environ.get(env_var)
        if val:
            result[key] = val

    result["max_commits"] = int(result["max_commits"])
    result["server_cache_ttl"] = int(result["server_cache_ttl"])
    return result


def read_server_url(folder):
    return read_config(folder).get("server_url")


def config_list_info(folder):
    """Return structured info about config sources and effective values for display."""
    folder_real = os.path.realpath(folder)
    ini_path = _find_covtest_ini(folder_real)
    candidates = [
        os.path.join(folder_real, "covtest.ini"),
        os.path.join(folder_real, "test", "covtest.ini"),
        os.path.join(folder_real, "tests", "covtest.ini"),
    ]
    env_entries = {env_var: os.environ.get(env_var) for env_var in _ENV_MAP}
    effective = read_config(folder_real)
    return {
        "config_file": ini_path,
        "candidates": candidates,
        "env": env_entries,
        "effective": effective,
    }
