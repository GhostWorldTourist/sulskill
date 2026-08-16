"""Run every test. `py tests/run.py` from anywhere.

A runner rather than only `python -m unittest`, because the audience for this
repository is Sims players, and "py tests/run.py" is something they can be
told over a forum post without a paragraph about discovery flags.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(HERE, top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
