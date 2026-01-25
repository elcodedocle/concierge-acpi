import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from request_validator import HostValidator

class TestHostValidator(unittest.TestCase):
    def test_validate_wakeup_host_with_mac(self):
        host_entry = {"hostname": "server1", "mac": "11:22:33:44:55:66"}
        error = HostValidator.validate_wakeup_host("server1", host_entry)
        self.assertIsNone(error)

    def test_validate_wakeup_host_without_mac(self):
        host_entry = {"hostname": "server1"}
        error = HostValidator.validate_wakeup_host("server1", host_entry)
        self.assertIsNotNone(error)
        self.assertEqual(error["hostname"], "server1")
        self.assertEqual(error["error"], "MAC not configured")

    def test_validate_command_host_shell_with_timeout(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "status",
                "type": "shell",
                "command": "ping",
                "arguments": ["-c1", "<hostname>"],
                "timeout": 30
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "status")
        self.assertIsNone(error)
        self.assertIsNotNone(cmd_data)
        cmd, timeout, is_sync = cmd_data
        self.assertEqual(cmd["name"], "status")
        self.assertEqual(timeout, 30)
        self.assertTrue(is_sync)

    def test_validate_command_host_shell_with_async_timeout(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "deploy",
                "type": "shell",
                "command": "ssh",
                "arguments": ["<hostname>", "deploy.sh"],
                "async_timeout": 120
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "deploy")
        self.assertIsNone(error)
        cmd, timeout, is_sync = cmd_data
        self.assertEqual(timeout, 120)
        self.assertFalse(is_sync)

    def test_validate_command_host_http_with_timeout(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "health",
                "type": "http",
                "url": "https://<hostname>/health",
                "method": "GET",
                "timeout": 10
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "health")
        self.assertIsNone(error)
        cmd, timeout, is_sync = cmd_data
        self.assertTrue(is_sync)
        self.assertEqual(timeout, 10)

    def test_validate_command_host_http_with_async_timeout(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "deploy",
                "type": "http",
                "url": "https://<hostname>/deploy",
                "method": "POST",
                "async_timeout": 300
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "deploy")
        self.assertIsNone(error)
        cmd, timeout, is_sync = cmd_data
        self.assertFalse(is_sync)
        self.assertEqual(timeout, 300)

    def test_validate_command_host_http_no_url(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "http",
                "method": "GET",
                "timeout": 10
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "test")
        self.assertIsNotNone(error)
        self.assertEqual(error["error"], "Invalid HTTP command: missing url")

    def test_validate_command_host_shell_no_command(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "arguments": ["-c1"],
                "timeout": 30
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "test")
        self.assertIsNotNone(error)
        self.assertEqual(error["error"], "Invalid command definition")

    def test_validate_command_host_command_not_found(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "status",
                "type": "shell",
                "command": "ping",
                "timeout": 30
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "nonexistent")
        self.assertIsNotNone(error)
        self.assertEqual(error["error"], "Command not allowed")

    def test_validate_command_host_invalid_timeout(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "command": "ping",
                "timeout": -5
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "test")
        self.assertIsNotNone(error)
        self.assertEqual(error["error"], "Invalid timeout")

    def test_validate_command_host_invalid_async_timeout(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "command": "ping",
                "async_timeout": -5
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "test")
        self.assertIsNotNone(error)
        self.assertEqual(error["error"], "Invalid async_timeout")

    def test_validate_command_host_missing_timeout(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "command": "ping"
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "test")
        self.assertIsNotNone(error)
        self.assertEqual(error["error"], "Missing timeout or async_timeout")

    def test_validate_command_host_unknown_type(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "unknown",
                "timeout": 30
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "test")
        self.assertIsNotNone(error)
        self.assertEqual(error["error"], "Unknown command type: unknown")

    def test_validate_hosts_wakeup_success(self):
        hosts_config = {
            "server1": {"mac": "11:22:33:44:55:66"},
            "server2": {"mac": "aa:bb:cc:dd:ee:ff"}
        }
        errors, entries = HostValidator.validate_hosts(
            ["server1", "server2"], "wakeup", None, hosts_config
        )
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(entries), 2)
        self.assertIn("server1", entries)
        self.assertIn("server2", entries)

    def test_validate_hosts_wakeup_host_not_allowed(self):
        hosts_config = {
            "server1": {"mac": "11:22:33:44:55:66"}
        }
        errors, entries = HostValidator.validate_hosts(
            ["server1", "unknown"], "wakeup", None, hosts_config
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["hostname"], "unknown")
        self.assertEqual(errors[0]["error"], "Host not allowed")
        self.assertEqual(len(entries), 1)

    def test_validate_hosts_command_success(self):
        hosts_config = {
            "server1": {
                "commands": [{
                    "name": "status",
                    "type": "shell",
                    "command": "ping",
                    "timeout": 30
                }]
            }
        }
        errors, entries = HostValidator.validate_hosts(
            ["server1"], "command", "status", hosts_config
        )
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(entries), 1)

    def test_validate_hosts_mixed_errors_and_success(self):
        hosts_config = {
            "server1": {"mac": "11:22:33:44:55:66"},
            "server2": {}
        }
        errors, entries = HostValidator.validate_hosts(
            ["server1", "server2", "server3"], "wakeup", None, hosts_config
        )
        self.assertEqual(len(errors), 2)
        self.assertEqual(len(entries), 1)

    def test_validate_hosts_async_timeout_minus_one(self):
        host_entry = {
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "command": "ping",
                "async_timeout": -1
            }]
        }
        error, cmd_data = HostValidator.validate_command_host("server1", host_entry, "test")
        self.assertIsNone(error)
        cmd, timeout, is_sync = cmd_data
        self.assertEqual(timeout, -1)
        self.assertFalse(is_sync)


if __name__ == '__main__':
    unittest.main()
