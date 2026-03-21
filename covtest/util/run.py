import subprocess


def run(cmd, ignore_error=False, cwd=None):
    result = subprocess.run(cmd, capture_output=True, cwd=cwd)
    stdout = result.stdout.decode("utf-8")
    stderr = result.stderr.decode("utf-8")

    if not ignore_error and result.returncode != 0:
        raise Exception("Unexpected error running %s: " % cmd, stdout, stderr)
    if ignore_error and result.returncode == 0:
        raise Exception("Unexpected success running %s: " % cmd, stdout, stderr)
    return stdout, stderr
