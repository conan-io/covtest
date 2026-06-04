from mypkg.helper import Helper

RESULT = Helper().compute(1, 2)   # module-level call: runs helper.py:3 on first import of sub
