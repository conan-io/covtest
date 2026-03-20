import unittest
from mymath import add, mult


class MyMathTest(unittest.TestCase):
    def test_add(self):
        b = add(2, 3)
        self.assertEqual(b, 5)

    def test_mult(self):
        b = mult(2, 3)
        self.assertEqual(b, 6)
