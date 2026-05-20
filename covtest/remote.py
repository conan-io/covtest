import base64
import logging
import os
import urllib.error
import urllib.request

from covtest.errors import CovTestException

logger = logging.getLogger(__name__)


def _auth_headers(user=None, password=None, token=None):
    """Build an Authorization header dict for the given credentials.

    Token auth takes precedence over basic auth when both are supplied.
    Returns an empty dict when no credentials are provided.
    """
    if token:
        return {"Authorization": f"Bearer {token}"}
    if user and password:
        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {creds}"}
    return {}


def upload(server_url, commit, covtest_file, user=None, password=None, token=None):
    """Upload a .covtest file to the remote server via HTTP PUT.

    Authentication priority: token > basic (user+password) > none.
    """
    url = "{}/{}.covtest".format(server_url.rstrip("/"), commit)
    logger.info("Uploading covtest data to %s", url)
    with open(covtest_file, "rb") as f:
        data = f.read()
    headers = _auth_headers(user, password, token)
    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            logger.info("Upload successful: %s", resp.status)
    except urllib.error.URLError as e:
        raise CovTestException("Failed to upload covtest data to {}: {}".format(url, e))


def download(server_url, commit, dest_dir, user=None, password=None, token=None):
    """Download a .covtest file from the remote server via HTTP GET.

    Authentication priority: token > basic (user+password) > none.
    Returns the local path on success, None if the file was not found or the
    server could not be reached.
    """
    url = "{}/{}.covtest".format(server_url.rstrip("/"), commit)
    dest = os.path.join(dest_dir, "{}.covtest".format(commit))
    logger.info("Downloading covtest data from %s", url)
    os.makedirs(dest_dir, exist_ok=True)
    headers = _auth_headers(user, password, token)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
        with open(dest, "wb") as f:
            f.write(data)
        logger.info("Downloaded covtest data to %s", dest)
        return dest
    except urllib.error.URLError as e:
        logger.warning("Could not download covtest data from %s: %s", url, e)
        return None
