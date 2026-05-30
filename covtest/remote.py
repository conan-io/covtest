import base64
import os

import requests

from covtest.errors import CovTestException
from covtest.output import out_warning, out_info


def _auth_headers(user=None, password=None, token=None):
    if token:
        return {"Authorization": f"Bearer {token}"}
    if user and password:
        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {creds}"}
    return {}


def upload(server_url, covtest_file, user=None, password=None, token=None):
    url = "{}/{}".format(server_url.rstrip("/"), os.path.basename(covtest_file))
    out_info(f"Uploading covtest data to {url}")
    with open(covtest_file, "rb") as f:
        data = f.read()
    headers = _auth_headers(user, password, token)
    try:
        resp = requests.put(url, data=data, headers=headers)
        resp.raise_for_status()
        out_info(f"Upload successful: {resp.status_code}")
    except requests.RequestException as e:
        raise CovTestException("Failed to upload covtest data to {}: {}".format(url, e))


def download(server_url, commit, dest_dir, user=None, password=None, token=None):
    url = "{}/{}.covtest".format(server_url.rstrip("/"), commit)
    dest = os.path.join(dest_dir, "{}.covtest".format(commit))
    out_info(f"Downloading covtest data from {url}")
    os.makedirs(dest_dir, exist_ok=True)
    headers = _auth_headers(user, password, token)
    try:
        resp = requests.get(url, headers=headers, allow_redirects=True)
        if resp.status_code == 404:
            out_warning(f"Could not download covtest data from {url}: 404 Not Found")
            return None
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)
        out_info(f"Downloaded covtest data to {dest}")
        return dest
    except requests.HTTPError as e:
        out_warning(f"HTTP error {e.response.status_code} {e.response.reason} from {url}")
        return None
    except requests.RequestException as e:
        out_warning(f"Could not download covtest data from {url}: {e}")
        return None
