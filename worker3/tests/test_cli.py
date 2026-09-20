import unittest

from worker3.cli import parse_args


class WorkerCliTests(unittest.TestCase):
    def test_slave_and_runner_flags(self):
        self.assertEqual(parse_args(["--slave", "G2gpu"]).slave, "G2gpu")
        self.assertEqual(parse_args(["--runner", "node-1"]).slave, "node-1")
        self.assertIsNone(parse_args([]).slave)
        self.assertFalse(parse_args([]).list_runners)
        self.assertTrue(parse_args(["--list-runners"]).list_runners)
        self.assertTrue(parse_args(["--list-slaves"]).list_runners)

    def test_schedule_flags(self):
        self.assertIsNone(parse_args([]).schedule)
        self.assertEqual(parse_args(["--fifo"]).schedule, "fifo")
        self.assertEqual(parse_args(["--schedule", "fifo"]).schedule, "fifo")
        self.assertEqual(parse_args(["--schedule", "greedy"]).schedule, "greedy")

    def test_predict_flags(self):
        self.assertIsNone(parse_args([]).predict)
        self.assertEqual(parse_args(["--predict", "base"]).predict, "base")
        self.assertEqual(parse_args(["--predict", "linear"]).predict, "linear")
        self.assertEqual(parse_args(["--predict-base"]).predict, "base")
        self.assertEqual(parse_args(["--predict-b"]).predict, "base")

    def test_n_retry_and_concise(self):
        args = parse_args(["--n-retry", "5", "--concise"])
        self.assertEqual(args.n_retry, 5)
        self.assertTrue(args.concise)

    def test_cli_logging_levels(self):
        defaults = parse_args([])
        self.assertFalse(defaults.verbose)
        self.assertIsNone(defaults.log_level)
        self.assertTrue(parse_args(["--verbose"]).verbose)
        self.assertTrue(parse_args(["-v"]).verbose)
        self.assertEqual(parse_args(["--log-level", "debug"]).log_level, "DEBUG")

    def test_logging_flags_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            parse_args(["--verbose", "--concise"])
        with self.assertRaises(SystemExit):
            parse_args(["--log-level", "INFO", "--verbose"])
