import pytest

from maya_plugin.handlers import ledger


class FakeCmds:
    """#799: a name this scene does not hold raises the way Maya raises.

    The ledger's only Maya surface is `xform`, and the old fake answered a
    missing name with a bare KeyError - a Python accident, not the
    RuntimeError("No object matches name: ...") a real session throws. The
    distinction matters because ledger.check() has no guard of its own: it
    is safe only because every caller resolves the name through
    naming.require_object first, and nothing pinned that.
    """

    def __init__(self):
        self.xforms = {}  # name -> (t, r, s)
        self.deleted = []

    def delete(self, *names):
        for name in names:
            self.deleted.append(name)
            # Removed from the table, NOT tombstoned: `deleted` is an audit
            # log and nothing consults it. A name re-created here (Maya lets
            # you rebuild a deleted object under its old name) is visible
            # again immediately, which a permanent tombstone would forbid -
            # a fake that is wrong in the STRICT direction, which #799
            # round 2 found elsewhere and which is no better than a
            # permissive one.
            self.xforms.pop(name, None)

    def xform(self, name, query=False, worldSpace=False, translation=False,
              rotation=False, scale=False, **kw):
        # #799 round 2: these two flags DEFAULTED TO TRUE, so the assert
        # below could not fail - `xform("|a", translation=(9, 9, 9))`, a
        # world-space WRITE with no query kwarg, passed it and was answered
        # with the old value as though it were a read. The guard was
        # decorative: deleting it changed no test. Defaulting both to False
        # is what makes it a guard, because that is how cmds.xform itself
        # defaults them - a write is exactly the call that omits query.
        assert query and worldSpace, (
            "the ledger only ever READS world space; a write reaches here as "
            "query=False and must not be answered with a stale read (%r)" % (kw or name,))
        assert not kw, "the ledger asks for t/r/s and nothing else, got %r" % (kw,)
        if name not in self.xforms:
            raise RuntimeError("No object matches name: %s" % name)
        t, r, s = self.xforms[name]
        if translation:
            return list(t)
        if rotation:
            return list(r)
        if scale:
            return list(s)
        raise AssertionError("unexpected xform query on %r" % name)


def test_check_without_record_is_none():
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
    assert ledger.check(fake, "|a") is None


def test_unchanged_transform_no_warning():
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((1, 2, 3), (0, 0, 0), (1, 1, 1))
    ledger.record(fake, "|a")
    assert ledger.check(fake, "|a") is None


def test_user_moved_object_warns_with_values():
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((1, 2, 3), (0, 0, 0), (1, 1, 1))
    ledger.record(fake, "|a")
    fake.xforms["|a"] = ((1, 2, 9), (0, 45, 0), (1, 1, 1))  # live user tumbled it
    warning = ledger.check(fake, "|a")
    assert warning is not None and "outside" in warning and "|a" in warning


def test_check_on_a_vanished_object_raises_rather_than_reporting():
    # #799 contract point 1, stated as a boundary rather than a defect.
    # ledger.check() reads the object unconditionally once it has a record,
    # so a name that no longer exists comes back as Maya's RuntimeError, not
    # as None and not as a warning. That is survivable ONLY because every
    # call site (modeling.transform, array.array) resolves the name through
    # naming.require_object first and so cannot reach here with a ghost.
    # Pinned so a future caller that skips that step fails here, loudly,
    # instead of in a live session.
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((1, 2, 3), (0, 0, 0), (1, 1, 1))
    ledger.record(fake, "|a")
    fake.delete("|a")
    with pytest.raises(RuntimeError, match="No object matches name"):
        ledger.check(fake, "|a")


def test_forgetting_an_object_makes_its_disappearance_harmless():
    # The counterpart: delete_objects/boolean_op call ledger.forget() on
    # everything they consume, and after that the vanished name is simply
    # unknown - no read, no raise.
    ledger.clear()
    fake = FakeCmds()
    fake.xforms["|a"] = ((1, 2, 3), (0, 0, 0), (1, 1, 1))
    ledger.record(fake, "|a")
    ledger.forget("|a")
    fake.delete("|a")
    assert ledger.check(fake, "|a") is None


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the hardening above had no test, so reverting it left
    the suite fully green - the very "a green suite proves nothing" failure
    this ticket exists to remove, moved up one level into the harness.

    These assert the contract points THIS fake models, and nothing else.
    The ledger's whole Maya surface is `cmds.xform` reads (grep confirms:
    ledger.py:19-21, three query=True calls and no writes anywhere), so
    there is no connection-fed plug, no locked plug and no setKeyframe to
    model here - the compound-direction and driven-key barriers belong to
    the fakes that actually own those calls.
    """

    def _live(self):
        fake = FakeCmds()
        fake.xforms["|a"] = ((1, 2, 3), (0, 0, 0), (1, 1, 1))
        return fake

    def test_a_query_about_a_deleted_node_raises(self):
        fake = self._live()
        fake.delete("|a")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.xform("|a", query=True, worldSpace=True, translation=True)

    def test_a_query_about_a_node_that_never_existed_raises(self):
        with pytest.raises(RuntimeError, match="No object matches name"):
            self._live().xform("|never", query=True, worldSpace=True,
                               translation=True)

    def test_a_world_space_write_is_refused_not_answered_with_a_stale_read(self):
        # The exact call a future ledger.restore() would make. Before the
        # round-2 fix this returned [1, 2, 3] - the OLD value - and the
        # handler's write vanished into a green test.
        fake = self._live()
        with pytest.raises(AssertionError, match="only ever READS"):
            fake.xform("|a", worldSpace=True, translation=(9, 9, 9))
        assert fake.xforms["|a"][0] == (1, 2, 3)  # and nothing was mutated

    def test_a_local_space_read_is_refused(self):
        # worldSpace omitted is object space, a different number entirely.
        with pytest.raises(AssertionError, match="world space"):
            self._live().xform("|a", query=True, translation=True)

    def test_a_flag_the_ledger_never_asks_for_is_refused(self):
        with pytest.raises(AssertionError, match="t/r/s and nothing else"):
            self._live().xform("|a", query=True, worldSpace=True,
                               rotatePivot=True)

    def test_deleting_a_name_does_not_tombstone_it_forever(self):
        # Maya lets an object be rebuilt under a name that was deleted. A
        # fake that remembered the deletion permanently would answer "No
        # object matches name" about a node that is standing right there -
        # strict-direction wrongness, which produces spurious failures the
        # next person "fixes" by weakening the fake back.
        fake = self._live()
        fake.delete("|a")
        fake.xforms["|a"] = ((7, 7, 7), (0, 0, 0), (1, 1, 1))
        assert fake.xform("|a", query=True, worldSpace=True,
                          translation=True) == [7, 7, 7]

    def test_the_guard_is_what_stands_between_check_and_a_silent_write(self):
        # End to end through the handler: ledger.check does three reads and
        # they all pass the guard, so the guard is not in the way of the
        # thing that legitimately uses it.
        ledger.clear()
        fake = self._live()
        ledger.record(fake, "|a")
        assert ledger.check(fake, "|a") is None


class TestRekeyFollowsARename:
    """#829: entries are keyed by long path, so renaming a node moves it and
    every descendant out from under their entries - measured live, where
    renaming |rig left |rig|kid_a and |rig|kid_b keyed to paths that no
    longer existed and the outside-edit check for them silently stopped."""

    class Cmds:
        def __init__(self, xf):
            self.xf = xf

        def xform(self, name, **kw):
            t, r, s = self.xf[name]
            if kw.get("translation"):
                return list(t)
            if kw.get("rotation"):
                return list(r)
            return list(s)

    def test_the_node_and_its_descendants_move_together(self):
        ledger.clear()
        cmds = self.Cmds({"|rig": ((0, 0, 0), (0, 0, 0), (1, 1, 1)),
                          "|rig|kid": ((1, 0, 0), (0, 0, 0), (1, 1, 1))})
        ledger.record(cmds, "|rig")
        ledger.record(cmds, "|rig|kid")
        ledger.rekey("|rig", "|lamp_rig")
        assert sorted(ledger._written) == ["|lamp_rig", "|lamp_rig|kid"]

    def test_the_recorded_values_are_kept_because_a_rename_moves_nothing(self):
        ledger.clear()
        cmds = self.Cmds({"|a": ((3, 2, 1), (0, 0, 0), (1, 1, 1))})
        ledger.record(cmds, "|a")
        before = ledger._written["|a"]
        ledger.rekey("|a", "|b")
        assert ledger._written["|b"] == before

    def test_a_name_that_merely_starts_the_same_is_left_alone(self):
        # |rig_spare is not under |rig, however it reads as a string.
        ledger.clear()
        cmds = self.Cmds({"|rig": ((0, 0, 0), (0, 0, 0), (1, 1, 1)),
                          "|rig_spare": ((0, 0, 0), (0, 0, 0), (1, 1, 1))})
        ledger.record(cmds, "|rig")
        ledger.record(cmds, "|rig_spare")
        ledger.rekey("|rig", "|lamp_rig")
        assert sorted(ledger._written) == ["|lamp_rig", "|rig_spare"]

    def test_rekeying_something_never_recorded_is_a_no_op(self):
        ledger.clear()
        ledger.rekey("|nothing", "|still_nothing")
        assert ledger._written == {}
