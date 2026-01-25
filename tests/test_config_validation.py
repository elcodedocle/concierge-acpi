import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from config_validation import validate_config_schema

class TestConfigValidation(unittest.TestCase):
    def test_validate_legacy_config_format(self):
        config = [
            {
                "hostname": "server1",
                "mac": "11:22:33:44:55:66",
                "commands": [
                    {
                        "name": "status",
                        "type": "shell",
                        "command": "ping",
                        "timeout": 30
                    }
                ]
            }
        ]
        
        # Should not raise
        validate_config_schema(config)

    def test_validate_new_config_format(self):
        config = {
            "hosts": [
                {
                    "hostname": "server1",
                    "mac": "11:22:33:44:55:66",
                    "commands": []
                }
            ],
            "execution_plans": []
        }
        
        # Should not raise
        validate_config_schema(config)

    def test_validate_invalid_top_level_type(self):
        with self.assertRaises(ValueError) as context:
            validate_config_schema("invalid")
        self.assertIn("must be an array or object", str(context.exception))

    def test_validate_hosts_missing_hostname(self):
        config = [{"mac": "11:22:33:44:55:66"}]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("missing required field 'hostname'", str(context.exception))

    def test_validate_hosts_invalid_mac(self):
        config = [{
            "hostname": "server1",
            "mac": "invalid-mac"
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("invalid MAC address", str(context.exception))

    def test_validate_hosts_valid_mac_with_colons(self):
        config = [{
            "hostname": "server1",
            "mac": "11:22:33:44:55:66"
        }]
        
        # Should not raise
        validate_config_schema(config)

    def test_validate_hosts_valid_mac_with_dashes(self):
        config = [{
            "hostname": "server1",
            "mac": "11-22-33-44-55-66"
        }]
        
        # Should not raise
        validate_config_schema(config)

    def test_validate_shell_command_missing_command(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "timeout": 30
            }]
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("missing 'command' field", str(context.exception))

    def test_validate_shell_command_missing_timeout(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "command": "ping"
            }]
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("must have 'timeout' or 'async_timeout'", str(context.exception))

    def test_validate_shell_command_with_async_timeout(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "shell",
                "command": "ping",
                "async_timeout": 120
            }]
        }]
        
        # Should not raise
        validate_config_schema(config)

    def test_validate_http_command_missing_url(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "http",
                "timeout": 30
            }]
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("missing 'url' field", str(context.exception))

    def test_validate_http_command_invalid_method(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "http",
                "url": "https://example.com",
                "method": "INVALID",
                "timeout": 30
            }]
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("invalid HTTP method", str(context.exception))

    def test_validate_http_command_invalid_payload_replacement(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "http",
                "url": "https://example.com",
                "payload_placeholder_replacement": "invalid_mode",
                "timeout": 30
            }]
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("invalid payload_placeholder_replacement", str(context.exception))

    def test_validate_http_command_conflicting_base64_replacement(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "http",
                "url": "https://example.com",
                "payload_base64_encoded": True,
                "payload_placeholder_replacement": "json_only",
                "timeout": 30
            }]
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("cannot use payload_placeholder_replacement with payload_base64_encoded", str(context.exception))

    def test_validate_execution_plans_missing_name(self):
        config = {
            "hosts": [],
            "execution_plans": [
                {
                    "tasks": []
                }
            ]
        }
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("missing 'name'", str(context.exception))

    def test_validate_execution_plans_missing_tasks(self):
        config = {
            "hosts": [],
            "execution_plans": [
                {
                    "name": "test_plan"
                }
            ]
        }
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("missing 'tasks'", str(context.exception))

    def test_validate_execution_plans_duplicate_names(self):
        config = {
            "hosts": [],
            "execution_plans": [
                {"name": "plan1", "tasks": []},
                {"name": "plan1", "tasks": []}
            ]
        }
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("Duplicate execution plan name", str(context.exception))

    def test_validate_execution_plan_task_missing_command(self):
        config = {
            "hosts": [],
            "execution_plans": [
                {
                    "name": "plan1",
                    "tasks": [
                        {
                            "hostnames": ["server1"]
                        }
                    ]
                }
            ]
        }
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("missing 'command'", str(context.exception))

    def test_validate_execution_plan_task_missing_hostnames(self):
        config = {
            "hosts": [],
            "execution_plans": [
                {
                    "name": "plan1",
                    "tasks": [
                        {
                            "command": "status"
                        }
                    ]
                }
            ]
        }
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("missing 'hostnames'", str(context.exception))

    def test_validate_complete_valid_config(self):
        config = {
            "hosts": [
                {
                    "hostname": "server1",
                    "mac": "11:22:33:44:55:66",
                    "commands": [
                        {
                            "name": "status",
                            "type": "shell",
                            "command": "ping",
                            "arguments": ["-c1", "<hostname>"],
                            "timeout": 30
                        },
                        {
                            "name": "api_call",
                            "type": "http",
                            "url": "https://<hostname>/api",
                            "method": "GET",
                            "timeout": 10
                        }
                    ]
                }
            ],
            "execution_plans": [
                {
                    "name": "health_check",
                    "referenced_plans": [],
                    "tasks": [
                        {
                            "command": "status",
                            "hostnames": ["server1"],
                            "params": {}
                        }
                    ]
                }
            ]
        }
        
        # Should not raise
        validate_config_schema(config)

    def test_validate_command_invalid_type(self):
        config = [{
            "hostname": "server1",
            "commands": [{
                "name": "test",
                "type": "invalid_type",
                "timeout": 30
            }]
        }]
        
        with self.assertRaises(ValueError) as context:
            validate_config_schema(config)
        self.assertIn("invalid type", str(context.exception))


if __name__ == '__main__':
    unittest.main()
