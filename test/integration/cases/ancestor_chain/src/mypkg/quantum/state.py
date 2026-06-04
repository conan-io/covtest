STATE_VALUE = 3     # no import from mypkg.util — so state.py contributes
                    # NO import_sources["mypkg"] entry with test context.
                    # Only the ancestor chain fix can attribute util.py:2 to
                    # the test that imports this file.
