
class MyMath:
    class Nested:
        def __init__(self):
            self.pi = "3.14"

        def value(self):
            return self.pi

    def __init__(self):
        self.msg = ""
        self.pi = MyMath.Nested().value()

    @staticmethod
    def add(a, b):
        return a + b  # some fix

    @staticmethod
    def mult(a, b):
        return a * b

    def license(self):
        self.msg = "Some license msg\n"
        self.msg += "Adding more info\n"


def some_math(v1, v2):
    def nested_function(a, b):
        c = a + b
        d = c + 1
        return d

    class NestedClass:
        def __init__(self):
            self.value = 1

        def add(self, v):
            self.value += v

    nestedc = NestedClass()
    nestedc.add(3)

    result = nested_function(v1, v2) + nestedc.value
    return result
