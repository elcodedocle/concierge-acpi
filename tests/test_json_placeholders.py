import unittest
import sys
import os
import json


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from task_executor_helper import replace_json_placeholders

class TestReplaceJsonPlaceholders(unittest.TestCase):
    def test_string_placeholder(self):
        json_text = '{"name": <string_name>}'
        result = replace_json_placeholders(json_text, "host1", {"name": "test-service"})
        expected = '{"name": "test-service"}'
        self.assertEqual(json.loads(result), json.loads(expected))

    def test_string_placeholder_with_special_chars(self):
        json_text = '{"message": <string_msg>}'
        result = replace_json_placeholders(json_text, "host1", {"msg": 'Hello "World"'})
        parsed = json.loads(result)
        self.assertEqual(parsed["message"], 'Hello "World"')

    def test_number_placeholder_integer(self):
        json_text = '{"count": <number_count>}'
        result = replace_json_placeholders(json_text, "host1", {"count": 42})
        expected = '{"count": 42}'
        self.assertEqual(json.loads(result), json.loads(expected))

    def test_number_placeholder_float(self):
        json_text = '{"value": <number_value>}'
        result = replace_json_placeholders(json_text, "host1", {"value": 3.14})
        expected = '{"value": 3.14}'
        self.assertEqual(json.loads(result), json.loads(expected))

    def test_number_placeholder_from_string(self):
        json_text = '{"port": <number_port>}'
        result = replace_json_placeholders(json_text, "host1", {"port": "8080"})
        expected = '{"port": 8080}'
        self.assertEqual(json.loads(result), json.loads(expected))

    def test_number_placeholder_rejects_boolean(self):
        json_text = '{"count": <number_count>}'
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"count": True})
        self.assertIn("cannot be converted to number", str(context.exception))

    def test_number_placeholder_rejects_non_numeric_string(self):
        json_text = '{"count": <number_count>}'
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"count": "abc"})
        self.assertIn("cannot be converted to number", str(context.exception))

    def test_boolean_placeholder_true(self):
        json_text = '{"enabled": <boolean_enabled>}'
        result = replace_json_placeholders(json_text, "host1", {"enabled": True})
        expected = '{"enabled": true}'
        self.assertEqual(json.loads(result), json.loads(expected))

    def test_boolean_placeholder_false(self):
        json_text = '{"enabled": <boolean_enabled>}'
        result = replace_json_placeholders(json_text, "host1", {"enabled": False})
        expected = '{"enabled": false}'
        self.assertEqual(json.loads(result), json.loads(expected))

    def test_boolean_placeholder_from_string_true(self):
        json_text = '{"flag": <boolean_flag>}'
        for value in ["true", "True", "TRUE", "1", "yes", "Yes", "YES"]:
            result = replace_json_placeholders(json_text, "host1", {"flag": value})
            parsed = json.loads(result)
            self.assertTrue(parsed["flag"])

    def test_boolean_placeholder_from_string_false(self):
        json_text = '{"flag": <boolean_flag>}'
        for value in ["false", "False", "FALSE", "0", "no", "No", "NO"]:
            result = replace_json_placeholders(json_text, "host1", {"flag": value})
            parsed = json.loads(result)
            self.assertFalse(parsed["flag"])

    def test_boolean_placeholder_rejects_invalid(self):
        json_text = '{"flag": <boolean_flag>}'
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"flag": "maybe"})
        self.assertIn("cannot be converted to boolean", str(context.exception))

    def test_json_placeholder_from_dict(self):
        json_text = '{"config": <json_config>}'
        config = {"key": "value", "nested": {"prop": 123}}
        result = replace_json_placeholders(json_text, "host1", {"config": config})
        parsed = json.loads(result)
        self.assertEqual(parsed["config"], config)

    def test_json_placeholder_from_string(self):
        json_text = '{"config": <json_config>}'
        config_str = '{"key": "value", "nested": {"prop": 123}}'
        result = replace_json_placeholders(json_text, "host1", {"config": config_str})
        parsed = json.loads(result)
        self.assertEqual(parsed["config"]["key"], "value")
        self.assertEqual(parsed["config"]["nested"]["prop"], 123)

    def test_json_placeholder_rejects_array(self):
        json_text = '{"config": <json_config>}'
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"config": [1, 2, 3]})
        self.assertIn("Must be a JSON object", str(context.exception))

    def test_json_placeholder_rejects_invalid_json(self):
        json_text = '{"config": <json_config>}'
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"config": "{invalid json}"})
        self.assertIn("not valid JSON", str(context.exception))

    def test_array_placeholder_from_list(self):
        json_text = '{"tags": <array_tags>}'
        tags = ["tag1", "tag2", "tag3"]
        result = replace_json_placeholders(json_text, "host1", {"tags": tags})
        parsed = json.loads(result)
        self.assertEqual(parsed["tags"], tags)

    def test_array_placeholder_from_string(self):
        json_text = '{"items": <array_items>}'
        items_str = '["item1", "item2", 3]'
        result = replace_json_placeholders(json_text, "host1", {"items": items_str})
        parsed = json.loads(result)
        self.assertEqual(parsed["items"], ["item1", "item2", 3])

    def test_array_placeholder_rejects_object(self):
        json_text = '{"tags": <array_tags>}'
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"tags": {"key": "value"}})
        self.assertIn("Must be a JSON array", str(context.exception))

    def test_array_placeholder_rejects_invalid_json(self):
        json_text = '{"tags": <array_tags>}'
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"tags": "[invalid]"})
        self.assertIn("not valid JSON array", str(context.exception))

    def test_hostname_placeholder(self):
        json_text = '{"host": <string_hostname>}'
        result = replace_json_placeholders(json_text, "server1.example.com", {})
        parsed = json.loads(result)
        self.assertEqual(parsed["host"], "server1.example.com")

    def test_multiple_placeholders(self):
        json_text = '{"name": <string_name>, "count": <number_count>, "enabled": <boolean_enabled>}'
        result = replace_json_placeholders(json_text, "host1", {
            "name": "test",
            "count": 5,
            "enabled": True
        })
        parsed = json.loads(result)
        self.assertEqual(parsed["name"], "test")
        self.assertEqual(parsed["count"], 5)
        self.assertTrue(parsed["enabled"])

    def test_nested_json_structure(self):
        json_text = '{"outer": {"inner": <string_value>, "list": [<number_num>, <boolean_flag>]}}'
        result = replace_json_placeholders(json_text, "host1", {
            "value": "test",
            "num": 42,
            "flag": True
        })
        parsed = json.loads(result)
        self.assertEqual(parsed["outer"]["inner"], "test")
        self.assertEqual(parsed["outer"]["list"][0], 42)
        self.assertTrue(parsed["outer"]["list"][1])

    def test_complex_nested_json(self):
        json_text = '{"metadata": <json_metadata>, "tags": <array_tags>}'
        metadata = {"author": "test", "version": 1}
        tags = ["prod", "critical"]
        result = replace_json_placeholders(json_text, "host1", {
            "metadata": metadata,
            "tags": tags
        })
        parsed = json.loads(result)
        self.assertEqual(parsed["metadata"], metadata)
        self.assertEqual(parsed["tags"], tags)

    def test_invalid_final_json_raises_error(self):
        # Create scenario where replacement creates invalid JSON
        json_text = '{"key": <string_value>'  # Missing closing brace
        with self.assertRaises(ValueError) as context:
            replace_json_placeholders(json_text, "host1", {"value": "test"})
        self.assertIn("not valid JSON", str(context.exception))

    def test_no_placeholders(self):
        json_text = '{"key": "value"}'
        result = replace_json_placeholders(json_text, "host1", {"unused": "param"})
        self.assertEqual(json.loads(result), json.loads(json_text))

    def test_missing_parameter(self):
        # Placeholder without corresponding parameter is left as-is
        json_text = '{"key": <string_value>}'
        # Should fail JSON validation since placeholder remains
        with self.assertRaises(ValueError):
            result = replace_json_placeholders(json_text, "host1", {})

    def test_unicode_in_string(self):
        json_text = '{"message": <string_msg>}'
        result = replace_json_placeholders(json_text, "host1", {"msg": "Hello 世界 🌍"})
        parsed = json.loads(result)
        self.assertEqual(parsed["message"], "Hello 世界 🌍")

    def test_empty_string(self):
        json_text = '{"value": <string_value>}'
        result = replace_json_placeholders(json_text, "host1", {"value": ""})
        parsed = json.loads(result)
        self.assertEqual(parsed["value"], "")

    def test_empty_array(self):
        json_text = '{"items": <array_items>}'
        result = replace_json_placeholders(json_text, "host1", {"items": []})
        parsed = json.loads(result)
        self.assertEqual(parsed["items"], [])

    def test_empty_object(self):
        json_text = '{"config": <json_config>}'
        result = replace_json_placeholders(json_text, "host1", {"config": {}})
        parsed = json.loads(result)
        self.assertEqual(parsed["config"], {})

    def test_number_with_decimal_string(self):
        json_text = '{"value": <number_value>}'
        result = replace_json_placeholders(json_text, "host1", {"value": "3.14159"})
        parsed = json.loads(result)
        self.assertAlmostEqual(parsed["value"], 3.14159)

    def test_string_placeholder_prevents_injection(self):
        # Attempt to inject JSON structure
        json_text = '{"data": <string_data>}'
        malicious = '", "injected": "value"}'
        result = replace_json_placeholders(json_text, "host1", {"data": malicious})
        parsed = json.loads(result)
        # Should be escaped and not create new key
        self.assertNotIn("injected", parsed)
        self.assertEqual(parsed["data"], malicious)

    def test_non_string_input_returns_as_is(self):
        result = replace_json_placeholders(123, "host1", {})
        self.assertEqual(result, 123)

    def test_case_sensitivity(self):
        json_text = '{"name": <string_Name>}'
        # Parameter is "Name" not "name"
        with self.assertRaises(ValueError):
            result = replace_json_placeholders(json_text, "host1", {"name": "test"})


if __name__ == '__main__':
    unittest.main()
