import ast

src = """\
import os

class MyMath:
    class Nested:
        def __init__(self):
            self.pi = "3.14"
    
    def __init__(self):
        self.msg = ""

    @staticmethod
    def add(a, b):
        return a + b

def some_math(v1, v2):
    a = v1 + v2
    return a
"""


def test_parse():
    lines = src.splitlines()
    print("\n" + "\n".join(f"{i}: {line}" for i, line in enumerate(lines)))

    rootnode = ast.parse(src)

    for node in ast.walk(rootnode):
        start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)
        print(node, start, end, lines[start-1:end] if start is not None else "")



