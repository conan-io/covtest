# Cases

- rm_test: Only removing 1 test from the suite. The result has still that test in the predicted tests
  the executor will pass it through ``pytest_collection_modifyitems()`` to not execute it.
