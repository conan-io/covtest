import builtins
import os

from nose.plugins import Plugin

from covtest.covtest_data import CovTestData


def patch_open(test, plugin):
    original_open = builtins.open

    def myopen(*args, **kwargs):
        plugin.add_file(args[0], test)
        return original_open(*args, **kwargs)
    builtins.open = myopen


class CovTestNosePlugin(Plugin):
    name = 'covtest_noseplugin'
    enabled = True

    def __init__(self, cov):
        self._cov = cov
        super(CovTestNosePlugin, self).__init__()
        self._original_open = builtins.open
        self._opened_files = {}

    def add_file(self, filename, test):
        self._opened_files.setdefault(filename, set()).add(test)

    def options(self, parser, env=os.environ):
        pass

    def startTest(self, test):
        address = test.address()
        full_name = "%s:%s" % (address[1], address[2])
        patch_open(full_name, self)
        self._cov.switch_context(full_name)

    def stopTest(self, test):
        builtins.open = self._original_open
        return

    def configure(self, options, conf):
        pass

    def save_opened_files(self, folder):
        result = {}
        for k, v in self._opened_files.items():
            path = os.path.relpath(k, folder)
            result[path] = v
        data = CovTestData(data_files=result)
        data.save(folder)

