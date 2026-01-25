import unittest
import tempfile
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from configuration import ConciergeConfig


class TestConciergeConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Create config file
        self.config_data = [
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
                        "name": "health",
                        "type": "http",
                        "url": "https://<hostname>/health",
                        "method": "GET",
                        "timeout": 10
                    }
                ]
            },
            {
                "hostname": "server2",
                "mac": "aa:bb:cc:dd:ee:ff",
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
        
        self.config_file = os.path.join(self.temp_dir, "config.json")
        with open(self.config_file, 'w') as f:
            json.dump(self.config_data, f)
        
        # Create template file
        self.template_file = os.path.join(self.temp_dir, "template.html")
        with open(self.template_file, 'w') as f:
            f.write("<html>{HOST_OPTIONS}{COMMAND_OPTIONS}</html>")
        
        # Create API spec file
        self.api_spec_file = os.path.join(self.temp_dir, "api_spec.yaml")
        with open(self.api_spec_file, 'w') as f:
            f.write("openapi: 3.0.0\ninfo:\n  title: Test API")

    def tearDown(self):
        for file in os.listdir(self.temp_dir):
            os.remove(os.path.join(self.temp_dir, file))
        os.rmdir(self.temp_dir)

    def test_init_loads_config(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertEqual(len(config.config), 2)
        self.assertIn("server1", config.hosts)
        self.assertIn("server2", config.hosts)

    def test_init_without_validation(self):
        # Test that we can disable validation
        config = ConciergeConfig(self.config_file, self.template_file, validate=False)
        self.assertIsNotNone(config)

    def test_init_with_dict_format(self):
        # New format with hosts and execution_plans
        dict_config = {
            "hosts": self.config_data,
            "execution_plans": []
        }
        
        dict_config_file = os.path.join(self.temp_dir, "dict_config.json")
        with open(dict_config_file, 'w') as f:
            json.dump(dict_config, f)
        
        config = ConciergeConfig(dict_config_file, self.template_file)
        self.assertEqual(len(config.config), 2)
        self.assertEqual(len(config.execution_plans), 0)

    def test_hosts_dictionary_created(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertEqual(config.hosts["server1"]["mac"], "11:22:33:44:55:66")
        self.assertEqual(config.hosts["server2"]["mac"], "aa:bb:cc:dd:ee:ff")

    def test_commands_dictionary_created(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertIn("status", config.commands)
        self.assertIn("health", config.commands)
        self.assertEqual(config.commands["status"]["type"], "shell")
        self.assertEqual(config.commands["health"]["type"], "http")

    def test_html_template_loaded(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertIsNotNone(config.html)
        self.assertNotIn("{HOST_OPTIONS}", config.html)
        self.assertNotIn("{COMMAND_OPTIONS}", config.html)

    def test_html_contains_host_options(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertIn("server1", config.html)
        self.assertIn("server2", config.html)
        self.assertIn('data-host="server1"', config.html)

    def test_html_contains_command_options(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertIn('value="health"', config.html)
        self.assertIn('value="status"', config.html)

    def test_api_spec_loaded(self):
        config = ConciergeConfig(self.config_file, self.template_file, self.api_spec_file)
        
        self.assertIsNotNone(config.api_spec)
        self.assertIn("openapi", config.api_spec)

    def test_api_spec_none_when_not_provided(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertIsNone(config.api_spec)

    def test_commands_sorted_in_html(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        # Find positions of command options in HTML
        health_pos = config.html.find('value="health"')
        status_pos = config.html.find('value="status"')
        
        # health should come before status alphabetically
        self.assertLess(health_pos, status_pos)

    def test_config_path_stored(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertEqual(config.config_path, self.config_file)

    def test_template_path_stored(self):
        config = ConciergeConfig(self.config_file, self.template_file)
        
        self.assertEqual(config.template_path, self.template_file)

    def test_api_spec_path_stored(self):
        config = ConciergeConfig(self.config_file, self.template_file, self.api_spec_file)
        
        self.assertEqual(config.api_spec_path, self.api_spec_file)

    def test_empty_config(self):
        empty_config_file = os.path.join(self.temp_dir, "empty_config.json")
        with open(empty_config_file, 'w') as f:
            json.dump([], f)
        
        config = ConciergeConfig(empty_config_file, self.template_file)
        
        self.assertEqual(len(config.hosts), 0)
        self.assertEqual(len(config.commands), 0)

    def test_host_without_commands(self):
        config_data = [
            {
                "hostname": "server1",
                "mac": "11:22:33:44:55:66"
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config2.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        config = ConciergeConfig(config_file, self.template_file)
        
        self.assertEqual(len(config.commands), 0)
        self.assertIn("server1", config.hosts)

    def test_duplicate_command_names_uses_first(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [
                    {"name": "status", "type": "shell", "command": "ping", "timeout": 10},
                    {"name": "status", "type": "http", "url": "https://example.com", "timeout": 20}
                ]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config3.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        config = ConciergeConfig(config_file, self.template_file)
        
        # setdefault should keep the first occurrence
        self.assertEqual(config.commands["status"]["type"], "shell")

    def test_html_special_characters_in_hostname(self):
        config_data = [
            {
                "hostname": "server<1>",
                "mac": "11:22:33:44:55:66"
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config4.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        config = ConciergeConfig(config_file, self.template_file)
        
        self.assertIn("server<1>", config.html)

    def test_validation_conflicting_base64_and_replacement(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": "SGVsbG8=",
                    "payload_base64_encoded": True,
                    "payload_placeholder_replacement": "json_only",
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_conflict.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        with self.assertRaises(ValueError) as context:
            ConciergeConfig(config_file, self.template_file)
            self.assertIn("Cannot use payload_placeholder_replacement with payload_base64_encoded", str(context.exception))

    def test_validation_very_unsafe_warning(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": '{"key": "<value>"}',
                    "payload_placeholder_replacement": "very_unsafe",
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_unsafe.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        import logging
        with self.assertLogs(level=logging.WARNING) as log:
            config = ConciergeConfig(config_file, self.template_file)
        
        self.assertTrue(any("very_unsafe" in message for message in log.output))
        self.assertTrue(any("can be abused" in message for message in log.output))

    def test_validation_json_only_info(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": '{"key": <string_value>}',
                    "payload_placeholder_replacement": "json_only",
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_json_only.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        import logging
        with self.assertLogs(level=logging.INFO) as log:
            config = ConciergeConfig(config_file, self.template_file)
        
        self.assertTrue(any("json_only" in message for message in log.output))

    def test_validation_disabled_no_warning(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": '{"key": "value"}',
                    "payload_placeholder_replacement": "disabled",
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_disabled.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        # Should not log any warnings
        config = ConciergeConfig(config_file, self.template_file)
        self.assertIsNotNone(config)

    def test_validation_default_disabled_no_warning(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": '{"key": "value"}',
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_default.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        # Should not log any warnings (defaults to disabled)
        config = ConciergeConfig(config_file, self.template_file)
        self.assertIsNotNone(config)

    def test_validation_base64_enabled_disabled_replacement_ok(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": "SGVsbG8=",
                    "payload_base64_encoded": True,
                    "payload_placeholder_replacement": "disabled",
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_base64_ok.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        # Should not raise error
        config = ConciergeConfig(config_file, self.template_file)
        self.assertIsNotNone(config)

    def test_validation_non_http_command_ignored(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test",
                    "type": "shell",
                    "command": "echo",
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_shell.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        # Should not validate shell commands
        config = ConciergeConfig(config_file, self.template_file)
        self.assertIsNotNone(config)

    def test_validation_multiple_hosts(self):
        config_data = [
            {
                "hostname": "server1",
                "commands": [{
                    "name": "test1",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": '{"key": "value"}',
                    "payload_placeholder_replacement": "very_unsafe",
                    "timeout": 30
                }]
            },
            {
                "hostname": "server2",
                "commands": [{
                    "name": "test2",
                    "type": "http",
                    "url": "https://example.com",
                    "payload": '{"key": <string_key>}',
                    "payload_placeholder_replacement": "json_only",
                    "timeout": 30
                }]
            }
        ]
        
        config_file = os.path.join(self.temp_dir, "config_multi.json")
        with open(config_file, 'w') as f:
            json.dump(config_data, f)
        
        import logging
        with self.assertLogs(level=logging.INFO) as log:
            config = ConciergeConfig(config_file, self.template_file)
        
        # Should log warnings/info for both
        self.assertTrue(any("server1" in message and "very_unsafe" in message for message in log.output))
        self.assertTrue(any("server2" in message and "json_only" in message for message in log.output))


if __name__ == '__main__':
    unittest.main()
