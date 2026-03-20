import os
import unittest

import pytest

from mymath import add, mult


class MyMathTest(unittest.TestCase):
    @pytest.mark.skipif(os.getenv("MY_COVTEST_OS") != "Windows", reason="only in Windows")
    def test_add(self):
        b = add(2, 3)
        self.assertEqual(b, 5)

    @pytest.mark.skipif(os.getenv("MY_COVTEST_OS") != "Linux", reason="only in Linux")
    def test_mult(self):
        b = mult(2, 3)
        self.assertEqual(b, 6)
