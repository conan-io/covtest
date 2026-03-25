import unittest

import pytest

from mymath import add, mult


class MyMathTest(unittest.TestCase):
    @pytest.mark.windows
    def test_add(self):
        b = add(2, 3)
        self.assertEqual(b, 5)

    @pytest.mark.linux
    def test_mult(self):
        b = mult(2, 3)
        self.assertEqual(b, 6)
