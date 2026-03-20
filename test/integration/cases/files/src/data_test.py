import unittest
from data import cities, countries


class DataTest(unittest.TestCase):
    def test_cities(self):
        t = cities()
        self.assertEqual(t, "London, New York")

    def test_countries(self):
        t = countries()
        self.assertEqual(t, "UK, France")
