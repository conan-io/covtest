import json
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


def continents():
    filename = os.path.join(os.path.dirname(__file__), "continents.json")
    with open(filename, "r") as f:
        data = json.load(f)
    result = data["continents"]
    return result
