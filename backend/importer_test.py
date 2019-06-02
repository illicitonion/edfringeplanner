import unittest

from importer import parse_time


class TestTimeParsing(unittest.TestCase):
    def test_one_hour(self):
        self.assertEqual("1:00:00", parse_time("1 hour"))

    def test_fifty_minutes(self):
        self.assertEqual("0:50:00", parse_time("50 minutes"))

    def test_one_hour_fifty_minutes(self):
        self.assertEqual("1:50:00", parse_time("1 hour 50 minutes"))

    def test_two_hours(self):
        self.assertEqual("2:00:00", parse_time("2 hours"))

    def test_wrong_tokens(self):
        with self.assertRaises(ValueError):
            parse_time("1")

    def test_unrecognised_units(self):
        with self.assertRaises(ValueError):
            parse_time("1 day 2 hours 3 minutes")


if __name__ == "__main__":
    unittest.main()
