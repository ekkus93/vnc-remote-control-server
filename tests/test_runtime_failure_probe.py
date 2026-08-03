import unittest


class RuntimeFailureProbe(unittest.TestCase):
    def test_ci_status_bridge_reports_a_real_failure(self):
        self.fail("intentional temporary CI status bridge failure probe")


if __name__ == "__main__":
    unittest.main()
