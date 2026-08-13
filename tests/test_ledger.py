from maya_plugin.handlers import ledger


class FakeCmds:
    def __init__(self):
        self.xforms = {}  # name -> (t, r, s)

    def xform(self, name, query=True, worldSpace=True, translation=False,
              rotation=False, scale=False):
        t, r, s = self.xforms[name]
        if translation:
            return list(t)
        if rotation:
            return list(r)
        return list(s)


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
