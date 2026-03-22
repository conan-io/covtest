import subprocess


def run(cmd, ignore_error=False, cwd=None):
    result = subprocess.run(cmd, capture_output=True, cwd=cwd, text=True)
    stdout = result.stdout
    stderr = result.stderr

    if not ignore_error and result.returncode != 0:
        raise Exception(f"Unexpected error running {cmd}: ", stdout, stderr)
    if ignore_error and result.returncode == 0:
        raise Exception(f"Unexpected success running {cmd}: ", stdout, stderr)
    return stdout, stderr
