import base64
import logging
import os

import requests

from covtest.errors import CovTestException

logger = logging.getLogger(__name__)


def _auth_headers(user=None, password=None, token=None):
    if token:
        return {"Authorization": f"Bearer {token}"}
    if user and password:
        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {creds}"}
    return {}


def upload(server_url, covtest_file, user=None, password=None, token=None):
    url = "{}/{}".format(server_url.rstrip("/"), os.path.basename(covtest_file))
    logger.info("Uploading covtest data to %s", url)
    with open(covtest_file, "rb") as f:
        data = f.read()
    headers = _auth_headers(user, password, token)
    try:
        resp = requests.put(url, data=data, headers=headers)
        resp.raise_for_status()
        logger.info("Upload successful: %s", resp.status_code)
    except requests.RequestException as e:
        raise CovTestException("Failed to upload covtest data to {}: {}".format(url, e))


def download(server_url, commit, dest_dir, user=None, password=None, token=None):
    url = "{}/{}.covtest".format(server_url.rstrip("/"), commit)
    dest = os.path.join(dest_dir, "{}.covtest".format(commit))
    logger.info("Downloading covtest data from %s", url)
    os.makedirs(dest_dir, exist_ok=True)
    headers = _auth_headers(user, password, token)
    try:
        resp = requests.get(url, headers=headers, allow_redirects=True)
        if resp.status_code == 404:
            logger.warning("Could not download covtest data from %s: 404 Not Found", url)
            return None
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)
        logger.info("Downloaded covtest data to %s", dest)
        return dest
    except requests.HTTPError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.reason}")
        print(e.response.text)
    except requests.RequestException as e:
        logger.warning("Could not download covtest data from %s: %s", url, e)
        print("Could not download covtest data from %s: %s", url, e)
        return None
