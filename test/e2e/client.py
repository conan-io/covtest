import io
import logging
import os
import tempfile

from covtest.cli import main
from covtest.util.files import load
from covtest.util.run import run


class TestClient:
    def __init__(self, cwd=None):
        self.cwd = cwd or tempfile.mkdtemp()
        self.out = ""

    def run_cmd(self, cmd):
        return run(cmd, cwd=self.cwd)

    def load(self, filename):
        return load(os.path.join(self.cwd, filename))

    def run(self, cmd):
        if isinstance(cmd, str):
            cmd = cmd.split(" ")

        # Get the ROOT logger (no name)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
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
        return result
