from data import cities, countries


def test_cities():
    t = cities()
    assert t == "London, New York"


def test_countries():
    t = countries()
    assert t == "UK, France"
