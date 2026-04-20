import configparser
import os

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


def read_server_url(folder):
    """Read covtest server_url from pyproject.toml or pytest.ini / setup.cfg."""
    if tomllib is not None:
        pyproject = os.path.join(folder, "pyproject.toml")
        if os.path.exists(pyproject):
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            url = data.get("tool", {}).get("covtest", {}).get("server_url")
            if url:
                return url

    for filename, section in [("pytest.ini", "pytest"), ("setup.cfg", "tool:pytest")]:
        cfg_path = os.path.join(folder, filename)
        if os.path.exists(cfg_path):
            cfg = configparser.ConfigParser()
            cfg.read(cfg_path)
            if cfg.has_option(section, "covtest_server"):
                return cfg.get(section, "covtest_server")

    return None
