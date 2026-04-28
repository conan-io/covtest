import subprocess


def run(cmd, ignore_error=False, cwd=None, env=None):
    result = subprocess.run(cmd, capture_output=True, cwd=cwd, text=True, env=env,
                            shell=isinstance(cmd, str))
    stdout = result.stdout
    stderr = result.stderr

    if not ignore_error and result.returncode != 0:
        print("\nSTDOUT:\n", stdout)
        print("\nSTDERR:\n", stderr)
        raise Exception(f"Unexpected error running {cmd}")
    if ignore_error and result.returncode == 0:
        print("\nSTDOUT:\n", stdout)
        print("\nSTDERR:\n", stderr)
        raise Exception(f"Unexpected success running {cmd}")
    return stdout, stderr
