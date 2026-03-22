import unittest
from mymath import mult  # Modify import, better test mult too


class MyMathTest(unittest.TestCase):

    def test_mult(self):
        b = mult(2, 3)
        self.assertEqual(b, 6)
