from __future__ import annotations

import unittest

from validation.retrieval_snapshot import SnapshotError, plan, simulate_switch


class SnapshotTests(unittest.TestCase):
    def test_rename_delete_and_audience_move_do_not_leave_old_units_active(self):
        old = {"release_id": "v1", "units": [
            {"audience": "business", "unit_id": "old-title"},
            {"audience": "business", "unit_id": "removed"},
            {"audience": "business", "unit_id": "moved"},
        ]}
        new = {"release_id": "v2", "units": [
            {"audience": "business", "unit_id": "new-title"},
            {"audience": "engineering", "unit_id": "moved"},
        ]}
        action = plan(old, new, "business")
        self.assertEqual(len(action["retire_keys"]), 3)
        self.assertEqual(action["stage_keys"], [("v2", "business", "new-title")])
        current = simulate_switch(old, new, "business")
        self.assertEqual(current["active_keys"], [("v2", "business", "new-title")])
        self.assertEqual(current["active_release_id"], "v2")

    def test_failed_stage_preserves_old_snapshot(self):
        old = {"release_id": "v1", "units": [{"audience": "business", "unit_id": "old"}]}
        new = {"release_id": "v2", "units": [{"audience": "business", "unit_id": "new"}]}
        result = simulate_switch(old, new, "business", fail_before_switch=True)
        self.assertEqual(result["active_release_id"], "v1")
        self.assertEqual(result["active_keys"], [("v1", "business", "old")])
        removed = simulate_switch(old, {"release_id": "v2", "units": []}, "business")
        self.assertEqual(removed["active_release_id"], "v2")
        self.assertEqual(removed["active_keys"], [])
        failed = simulate_switch(old, {"release_id": "v2", "units": []}, "business", fail_before_switch=True)
        self.assertEqual(failed["active_keys"], [("v1", "business", "old")])


if __name__ == "__main__":
    unittest.main()
