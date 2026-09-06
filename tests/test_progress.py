"""maya_plugin.progress - the stage a long handler reports (redmine #836).

The kethran run's 40-minute bake answered every later request with a
BusyError whose only signal was the elapsed seconds; the stage ("map 2 of
3: curvature 2048 for body") is the missing half. A handler writes it here
from Maya's main thread; the dispatcher reads it from the socket thread
while building the hint, and clears it around every job so a stage never
outlives the command that reported it.
"""

import time

from maya_plugin import progress


def setup_function(_fn):
    progress.clear()


def test_nothing_reported_is_none():
    assert progress.current() is None


def test_a_report_is_readable_with_how_long_it_has_stood():
    progress.report("map 1 of 3: ao 512 for body")
    stage, for_s = progress.current()
    assert stage == "map 1 of 3: ao 512 for body"
    assert 0.0 <= for_s < 1.0
    time.sleep(0.06)  # Windows' monotonic ticks at ~16 ms
    assert progress.current()[1] >= 0.03


def test_a_newer_report_replaces_and_restarts_the_clock():
    progress.report("first")
    time.sleep(0.06)
    progress.report("second")
    stage, for_s = progress.current()
    assert stage == "second"
    assert for_s < 0.03


def test_clear_forgets_it():
    progress.report("x")
    progress.clear()
    assert progress.current() is None


def test_a_blank_report_counts_as_clearing():
    progress.report("x")
    progress.report("")
    assert progress.current() is None
