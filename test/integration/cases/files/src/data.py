import os


def cities():
    filename = os.path.join(os.path.dirname(__file__), "cities.txt")
    with open(filename, "r") as f:
        content = f.read()
    return content


def countries():
    filename = os.path.join(os.path.dirname(__file__), "countries.txt")
    with open(filename, "r") as f:
        content = f.read()
    return content
