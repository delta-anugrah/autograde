"""Run only by `test_browser_harness.py` (no `test_` prefix, so never collected on its own).

One page that throws a script error: the guard must fail THIS test in its call phase, so
pytest-playwright keeps the trace and screenshot. A guard that trips in teardown reports
"passed" plus an error, and pytest-playwright then keeps nothing.
"""

from __future__ import annotations

import langkah  # noqa: F401  (same skip-or-fail switch as the real tests)


def test_a_page_that_throws(halaman):
    halaman.evaluate("() => { setTimeout(() => { throw new Error('probe error'); }, 0); }")
    halaman.evaluate("() => new Promise((r) => setTimeout(r, 300))")
