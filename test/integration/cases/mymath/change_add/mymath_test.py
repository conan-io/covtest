import unittest
from mymath import addition, mult


class MyMathTest(unittest.TestCase):
    def test_add(self):
        b = addition(2, 3)
        self.assertEqual(b, 5)

    def test_mult(self):
        b = mult(2, 3)
        self.assertEqual(b, 6)
