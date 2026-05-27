import base64
import os
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from test.e2e.client import TestClient
from test.integration.test_cases_utils import prepare_src_folder, git_init_repo, do_code_changes


class _FileServerHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler: PUT stores files, GET serves them."""

    def do_PUT(self):  # noqa
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)
        dest = os.path.join(self.server.root_dir, self.path.lstrip("/"))  # noqa
        os.makedirs(os.path.dirname(dest) or self.server.root_dir, exist_ok=True)  # noqa
        with open(dest, "wb") as f:
            f.write(data)
        self.send_response(201)
        self.end_headers()

    def do_GET(self):  # noqa
        path = os.path.join(self.server.root_dir, self.path.lstrip("/"))    # noqa
        if not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):   # noqa
        pass  # suppress test output noise


class _AuthFileServerHandler(_FileServerHandler):
    """File server that requires authentication (basic or bearer token).

    Configured via ``server.expected_token`` and/or
    ``server.expected_user`` / ``server.expected_password``.
    Returns HTTP 401 when the Authorization header is missing or wrong.
    """

    def _check_auth(self):
        auth = self.headers.get("Authorization", "")
        # Bearer token
        expected_token = getattr(self.server, "expected_token", None)  # noqa
        if expected_token and auth == f"Bearer {expected_token}":
            return True
        # Basic auth
        expected_user = getattr(self.server, "expected_user", None)     # noqa
        expected_password = getattr(self.server, "expected_password", None)  # noqa
        if expected_user and expected_password:
            creds = base64.b64encode(
                f"{expected_user}:{expected_password}".encode()
            ).decode()
            if auth == f"Basic {creds}":
                return True
        return False

    def do_PUT(self):  # noqa
        if not self._check_auth():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="covtest"')
            self.end_headers()
            return
        super().do_PUT()

    def do_GET(self):  # noqa
        if not self._check_auth():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="covtest"')
            self.end_headers()
            return
        super().do_GET()


def _start_file_server(root_dir):
    server = HTTPServer(("127.0.0.1", 0), _FileServerHandler)
    server.root_dir = root_dir
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server


def _start_auth_file_server(root_dir, expected_token=None,
                             expected_user=None, expected_password=None):
    server = HTTPServer(("127.0.0.1", 0), _AuthFileServerHandler)
    server.root_dir = root_dir
    server.expected_token = expected_token
    server.expected_user = expected_user
    server.expected_password = expected_password
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server


def test_remote_upload_and_download():
    """Full CI → dev flow using a local HTTP file server."""
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    commit = git_init_repo(src_folder)
    commit = commit.strip()

    # --- CI side: run tests, process coverage ---
    out, err = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out

    c.run("process")
    assert "covtest: done" in c.out

    covtest_dir = os.path.join(src_folder, ".covtest")
    assert os.path.isfile(os.path.join(covtest_dir, f"{commit}.covtest"))

    # Start a local HTTP file server
    server_root = tempfile.mkdtemp()
    server = _start_file_server(server_root)
    server_url = f"http://127.0.0.1:{server.server_address[1]}"

    # Write server URL into covtest.ini so CLI commands and the plugin pick it up
    c.save({"covtest.ini": f"[covtest]\nserver_url = {server_url}\n"})

    try:
        # --- CI side: upload ---
        c.run("upload")
        assert "Upload successful" in c.out
        assert os.path.isfile(os.path.join(server_root, f"{commit}.covtest"))

        # --- Dev side: start fresh, no local covtest data ---
        shutil.rmtree(covtest_dir)
        assert not os.path.isdir(covtest_dir)

        do_code_changes(src_folder, "mymath/fix_add")

        # First predict: downloads from server, reports the commit gap
        c.run("predict .")
        assert f"Downloading covtest data from {server_url}/{commit}.covtest" in c.out
        assert "0 commit(s) back" in c.out
        assert "mymath_test.py::MyMathTest::test_add" == c.load(".covtest/covtests.tests")

        # The file is now cached locally
        assert os.path.isfile(os.path.join(covtest_dir, f"{commit}.covtest"))

        # Second predict: uses local cache, no download
        c.run("predict .")
        assert f"Downloading covtest data from {server_url}" not in c.out
        assert "mymath_test.py::MyMathTest::test_add" == c.load(".covtest/covtests.tests")

    finally:
        server.shutdown()
        shutil.rmtree(server_root)


def test_remote_auth_token_cli():
    """Upload via --token CLI arg; download via COVTEST_TOKEN env var."""
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    commit = git_init_repo(src_folder).strip()

    out, _ = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out
    c.run("process")
    assert "covtest: done" in c.out

    server_root = tempfile.mkdtemp()
    token = "secret-token-abc123"
    server = _start_auth_file_server(server_root, expected_token=token)
    server_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        # --- Upload with --url and --token CLI args (no covtest.ini needed) ---
        c.run(f"upload --url {server_url} --token {token}")
        assert "Upload successful" in c.out
        assert os.path.isfile(os.path.join(server_root, f"{commit}.covtest"))

        # --- Unauthenticated upload should fail ---
        c.run("upload --url " + server_url, assert_error=True)
        assert "Failed to upload" in c.out

        # --- Download via COVTEST_URL + COVTEST_TOKEN env vars ---
        covtest_dir = os.path.join(src_folder, ".covtest")
        shutil.rmtree(covtest_dir)
        do_code_changes(src_folder, "mymath/fix_add")

        old_env = {k: os.environ.get(k) for k in ("COVTEST_URL", "COVTEST_TOKEN")}
        os.environ["COVTEST_URL"] = server_url
        os.environ["COVTEST_TOKEN"] = token
        try:
            c.run("predict .")
            assert f"Downloading covtest data from {server_url}/{commit}.covtest" in c.out
            assert "mymath_test.py::MyMathTest::test_add" == c.load(".covtest/covtests.tests")
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    finally:
        server.shutdown()
        shutil.rmtree(server_root)


def test_remote_auth_basic_cli():
    """Upload via --user/--password CLI args; download via covtest.ini credentials."""
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    commit = git_init_repo(src_folder).strip()

    out, _ = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out
    c.run("process")
    assert "covtest: done" in c.out

    server_root = tempfile.mkdtemp()
    user, password = "ci-user", "ci-pass"
    server = _start_auth_file_server(server_root, expected_user=user,
                                     expected_password=password)
    server_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        # --- Upload with --url, --user, --password (no covtest.ini) ---
        c.run(f"upload --url {server_url} --user {user} --password {password}")
        assert "Upload successful" in c.out
        assert os.path.isfile(os.path.join(server_root, f"{commit}.covtest"))

        # --- Download with credentials in covtest.ini ---
        covtest_dir = os.path.join(src_folder, ".covtest")
        shutil.rmtree(covtest_dir)
        do_code_changes(src_folder, "mymath/fix_add")

        c.save({
            "covtest.ini": (
                f"[covtest]\n"
                f"server_url = {server_url}\n"
                f"auth_user = {user}\n"
                f"auth_password = {password}\n"
            )
        })
        c.run("predict .")
        assert f"Downloading covtest data from {server_url}/{commit}.covtest" in c.out
        assert "mymath_test.py::MyMathTest::test_add" == c.load(".covtest/covtests.tests")

    finally:
        server.shutdown()
        shutil.rmtree(server_root)


def test_remote_auth_env_vars():
    """All auth settings via env vars only — no covtest.ini, no CLI flags."""
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    commit = git_init_repo(src_folder).strip()

    out, _ = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out
    c.run("process")

    server_root = tempfile.mkdtemp()
    user, password = "env-user", "env-pass"
    server = _start_auth_file_server(server_root, expected_user=user,
                                     expected_password=password)
    server_url = f"http://127.0.0.1:{server.server_address[1]}"

    env_keys = ("COVTEST_URL", "COVTEST_USER", "COVTEST_PASSWORD")
    old_env = {k: os.environ.get(k) for k in env_keys}
    os.environ["COVTEST_URL"] = server_url
    os.environ["COVTEST_USER"] = user
    os.environ["COVTEST_PASSWORD"] = password
    try:
        # Upload: no --url, no ini; all from env
        c.run("upload")
        assert "Upload successful" in c.out
        assert os.path.isfile(os.path.join(server_root, f"{commit}.covtest"))

        # Download: also from env
        covtest_dir = os.path.join(src_folder, ".covtest")
        shutil.rmtree(covtest_dir)
        do_code_changes(src_folder, "mymath/fix_add")

        c.run("predict .")
        assert f"Downloading covtest data from {server_url}/{commit}.covtest" in c.out
        assert "mymath_test.py::MyMathTest::test_add" == c.load(".covtest/covtests.tests")

    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        server.shutdown()
        shutil.rmtree(server_root)
