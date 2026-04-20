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

    # Write server URL into pyproject.toml so CLI commands pick it up
    c.save({"pyproject.toml": f'[tool.covtest]\nserver_url = "{server_url}"\n'})

    try:
        # --- CI side: upload ---
        c.run("upload")
        assert "Upload successful" in c.out
        assert os.path.isfile(os.path.join(server_root, f"{commit}.covtest"))

        # --- Dev side: start fresh, no local covtest data ---
        shutil.rmtree(covtest_dir)
        assert not os.path.isdir(covtest_dir)

        do_code_changes(src_folder, "mymath/fix_add")

        # predict should auto-download from server and filter correctly
        c.run("predict .")
        assert f"Downloading covtest data from {server_url}/{commit}.covtest" in c.out
        assert "mymath_test.py::MyMathTest::test_add" == c.load("covtests.tests")

        # Verify the file was restored locally after download
        assert os.path.isfile(os.path.join(covtest_dir, f"{commit}.covtest"))

        # A new predict doesn't download again
        c.run("predict .")
        assert f"Downloading covtest data from {server_url}/{commit}.covtest" not in c.out
        assert "mymath_test.py::MyMathTest::test_add" == c.load("covtests.tests")

    finally:
        server.shutdown()
        shutil.rmtree(server_root)
