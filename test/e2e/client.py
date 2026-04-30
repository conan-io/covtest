import gzip
import io
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager

from covtest.cli import main
from covtest.util.files import load, save
from covtest.util.run import run


class TestClient:
    def __init__(self, cwd=None):
        self.cwd = cwd or tempfile.mkdtemp()
        self.out = ""

    def run_cmd(self, cmd, env=None, assert_error=False):
        return run(cmd, cwd=self.cwd, env=env, ignore_error=assert_error)

    def save(self, files):
        for f, content in files.items():
            save(os.path.join(self.cwd, f), str(content))

    def rm(self, file):
        os.remove(os.path.join(self.cwd, file))

    @contextmanager
    def chdir(self, path):
        cwd = self.cwd
        try:
            self.cwd = os.path.join(self.cwd, path)
            yield
        finally:
            self.cwd = cwd

    def load(self, filename):
        return load(os.path.join(self.cwd, filename))

    def loadgz(self, filename):
        with gzip.open(os.path.join(self.cwd, filename), "rt", encoding="utf-8") as fh:
            data = fh.read()
        return data

    def mv(self, src, dst):
        os.makedirs(os.path.dirname(os.path.join(self.cwd, dst)), exist_ok=True)
        shutil.move(os.path.join(self.cwd, src), os.path.join(self.cwd, dst))

    def run(self, cmd, assert_error=False):
        if isinstance(cmd, str):
            cmd = cmd.split(" ")
        cmd = [c for c in cmd if c]

        # Get the ROOT logger (no name)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        log_buffer = io.StringIO()
        handler = logging.StreamHandler(log_buffer)
        root_logger.handlers = []
        root_logger.addHandler(handler)

        cwd = os.getcwd()
        try:
            os.chdir(self.cwd)
            result = main(cmd)
        finally:
            os.chdir(cwd)
        self.out = log_buffer.getvalue()

        if result == 0 and assert_error:
            raise Exception(f"Failure expected {cwd}\n{self.out}\n")
        if result != 0 and not assert_error:
            raise Exception(f"Command failed unexpectedly: {cmd}:\n{self.out}\n")
        return result
