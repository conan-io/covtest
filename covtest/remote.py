import logging
import os
import urllib.error
import urllib.request

from covtest.errors import CovTestException

logger = logging.getLogger(__name__)


def upload(server_url, commit, covtest_file):
    """Upload a .covtest file to the remote server via HTTP PUT."""
    url = "{}/{}.covtest".format(server_url.rstrip("/"), commit)
    logger.info("Uploading covtest data to %s", url)
    with open(covtest_file, "rb") as f:
        data = f.read()
    req = urllib.request.Request(url, data=data, method="PUT")
    try:
        with urllib.request.urlopen(req) as resp:
            logger.info("Upload successful: %s", resp.status)
    except urllib.error.URLError as e:
        raise CovTestException("Failed to upload covtest data to {}: {}".format(url, e))


def download(server_url, commit, dest_dir):
    """Download a .covtest file from the remote server via HTTP GET.

    Returns the local path on success, None if the file was not found or the
    server could not be reached.
    """
    url = "{}/{}.covtest".format(server_url.rstrip("/"), commit)
    dest = os.path.join(dest_dir, "{}.covtest".format(commit))
    logger.info("Downloading covtest data from %s", url)
    os.makedirs(dest_dir, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
        logger.info("Downloaded covtest data to %s", dest)
        return dest
    except urllib.error.URLError as e:
        logger.warning("Could not download covtest data from %s: %s", url, e)
        return None
