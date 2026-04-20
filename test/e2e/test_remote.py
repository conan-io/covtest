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


def _start_file_server(root_dir):
    server = HTTPServer(("127.0.0.1", 0), _FileServerHandler)
    server.root_dir = root_dir
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
    assert "Processing done" in c.out

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
        assert "mymath_test.py::MyMathTest::test_add" == c.load("covtests.tests")

        # The file is now cached locally
        assert os.path.isfile(os.path.join(covtest_dir, f"{commit}.covtest"))

        # Second predict: uses local cache, no download
        c.run("predict .")
        assert f"Downloading covtest data from {server_url}" not in c.out
        assert "mymath_test.py::MyMathTest::test_add" == c.load("covtests.tests")

    finally:
        server.shutdown()
        shutil.rmtree(server_root)


def test_negative_cache():
    """Commits absent from the server are not re-queried within the TTL."""
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    git_init_repo(src_folder)

    # Server exists but has no data
    server_root = tempfile.mkdtemp()
    server = _start_file_server(server_root)
    server_url = f"http://127.0.0.1:{server.server_address[1]}"

    # Short TTL so the test stays fast; large enough we won't expire during the test
    c.save({"covtest.ini": f"[covtest]\nserver_url = {server_url}\nserver_cache_ttl = 60\n"})

    try:
        out, err = c.run_cmd("pytest --cov=. --cov-context=test")
        assert "2 passed" in out
        c.run("process")

        covtest_dir = os.path.join(src_folder, ".covtest")
        shutil.rmtree(covtest_dir, ignore_errors=True)

        do_code_changes(src_folder, "mymath/fix_add")

        # First predict: queries server, finds nothing, writes negative cache
        c.run("predict .", assert_error=True)  # returns -1, no data
        assert "Checking server for covtest data" in c.out
        not_found_cache = os.path.join(src_folder, ".covtest", "server_not_found.json")
        not_found = c.load(".covtest/server_not_found.json")
        print(not_found)
        assert os.path.isfile(not_found_cache)

        # Second predict: skips server entirely (negative cache still valid)
        c.run("predict .", assert_error=True)
        assert "Checking server for covtest data" not in c.out
        assert "cached not-found" in c.out

    finally:
        server.shutdown()
        shutil.rmtree(server_root)
