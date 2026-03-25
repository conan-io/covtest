import os


def add(a, b):
    if os.getenv("MY_COVTEST_OS") != "Windows":
        raise Exception("This function only works in Windows")
    return a + b


def mult(a, b):
    if os.getenv("MY_COVTEST_OS") != "Linux":
        raise Exception("This function only works in Linux")
    return a * b  # fixed in Linux
