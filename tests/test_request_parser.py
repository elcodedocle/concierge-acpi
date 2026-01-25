import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from request_validator import RequestParser

class TestRequestParser(unittest.TestCase):
    def test_parse_wakeup_no_hostname(self):
        path = "/concierge/api/v1/wakeup"
        action, command, hostname = RequestParser.parse_post_path(path)
        self.assertEqual(action, "wakeup")
        self.assertIsNone(command)
        self.assertIsNone(hostname)

    def test_parse_wakeup_with_hostname(self):
        path = "/concierge/api/v1/wakeup/server1"
        action, command, hostname = RequestParser.parse_post_path(path)
        self.assertEqual(action, "wakeup")
        self.assertIsNone(command)
        self.assertEqual(hostname, "server1")

    def test_parse_command_no_hostname(self):
        path = "/concierge/api/v1/commands/status"
        action, command, hostname = RequestParser.parse_post_path(path)
        self.assertEqual(action, "command")
        self.assertEqual(command, "status")
        self.assertIsNone(hostname)

    def test_parse_command_with_hostname(self):
        path = "/concierge/api/v1/commands/restart/server1"
        action, command, hostname = RequestParser.parse_post_path(path)
        self.assertEqual(action, "command")
        self.assertEqual(command, "restart")
        self.assertEqual(hostname, "server1")

    def test_parse_invalid_path_too_short(self):
        path = "/concierge/api"
        with self.assertRaises(ValueError) as context:
            RequestParser.parse_post_path(path)
        self.assertIn("Invalid API path", str(context.exception))

    def test_parse_invalid_action(self):
        path = "/concierge/api/v1/invalid/action"
        with self.assertRaises(ValueError) as context:
            RequestParser.parse_post_path(path)
        self.assertIn("Invalid API path", str(context.exception))

    def test_parse_wakeup_too_many_parts(self):
        path = "/concierge/api/v1/wakeup/server1/extra"
        with self.assertRaises(ValueError) as context:
            RequestParser.parse_post_path(path)
        self.assertIn("Invalid API path", str(context.exception))

    def test_parse_command_too_many_parts(self):
        path = "/concierge/api/v1/commands/status/server1/extra"
        with self.assertRaises(ValueError) as context:
            RequestParser.parse_post_path(path)
        self.assertIn("Invalid API path", str(context.exception))

    def test_parse_path_with_leading_trailing_slashes(self):
        path = "//concierge/api/v1/wakeup/server1//"
        action, command, hostname = RequestParser.parse_post_path(path)
        self.assertEqual(action, "wakeup")
        self.assertIsNone(command)
        # Note: Will have empty strings from split, depends on implementation

    def test_parse_command_missing_command_name(self):
        path = "/concierge/api/v1/commands"
        with self.assertRaises(ValueError):
            RequestParser.parse_post_path(path)


if __name__ == '__main__':
    unittest.main()
