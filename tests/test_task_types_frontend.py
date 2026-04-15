import unittest
from pathlib import Path


class TaskTypesFrontendTests(unittest.TestCase):
    def test_task_types_color_popover_uses_stable_anchor_for_outside_click_detection(self):
        source = Path("static/task_types.js").read_text()

        self.assertIn('data-role="color-popover-anchor"', source)
        self.assertIn("closest('[data-role=\"color-popover-anchor\"]')", source)


if __name__ == "__main__":
    unittest.main()
