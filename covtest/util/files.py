import hashlib
import os
from contextlib import contextmanager


@contextmanager
def chdir(folder):
    current = os.getcwd()
    os.chdir(folder)
    try:
        yield
    finally:
        os.chdir(current)


def load(filepath):
    with open(filepath, "r") as f:
        content = f.read()
    return content


def save(filepath, content):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
