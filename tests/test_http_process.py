import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from persistent_dictionary import OptionallyPersistentOrderedThreadSafeDict
from task_executor import HTTPProcess

class TestHTTPProcess(unittest.TestCase):
    def setUp(self):
        self.db = OptionallyPersistentOrderedThreadSafeDict()
        self.task_id = "test-task-123"
        self.hostname = "api.example.com"
        
        self.db[self.task_id] = {
            "task_id": self.task_id,
            "command": "health_check",
            "success": [],
            "running": [{"hostname": self.hostname}],
            "errors": [],
            "start_timestamp": 1234567890
        }

    @patch('concierge_acpi.HTTPSConnection')
    def test_abort_before_execution(self, mock_conn_class):
        config = {
            "method": "GET",
            "url": "https://<hostname>/api",
            "timeout": 30
        }

        process = HTTPProcess(self.task_id, self.hostname, config, None, self.db)
        process.abort()
        process.run_sync()

        # Should not make any requests
        mock_conn_class.assert_not_called()

    @patch('concierge_acpi.HTTPSConnection')
    def test_payload_replacement_invalid_mode(self, mock_conn_class):
        mock_conn = MagicMock()
        mock_conn_class.return_value = mock_conn

        config = {
            "method": "POST",
            "url": "https://<hostname>/api",
            "payload": '{"key": "value"}',
            "payload_placeholder_replacement": "invalid_mode",
            "timeout": 30
        }

        process = HTTPProcess(self.task_id, self.hostname, config, None, self.db)
        process.run_sync()

        # Should record error
        task = self.db[self.task_id]
        self.assertEqual(len(task["errors"]), 1)
        self.assertIn("Unknown payload_placeholder_replacement mode", task["errors"][0]["error"])

    @patch('concierge_acpi.HTTPSConnection')
    def test_payload_replacement_json_only_invalid_json(self, mock_conn_class):
        mock_conn = MagicMock()
        mock_conn_class.return_value = mock_conn

        config = {
            "method": "POST",
            "url": "https://<hostname>/api",
            "payload": '{"key": <string_value>',  # Invalid JSON
            "payload_placeholder_replacement": "json_only",
            "timeout": 30
        }

        process = HTTPProcess(self.task_id, self.hostname, config, {"value": "test"}, self.db)
        process.run_sync()

        # Should record error about invalid JSON
        task = self.db[self.task_id]
        self.assertEqual(len(task["errors"]), 1)
        self.assertIn("not valid JSON", task["errors"][0]["error"])

    @patch('concierge_acpi.HTTPSConnection')
    @patch('threading.Thread')
    def test_run_async(self, mock_thread, mock_conn_class):
        mock_conn = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'OK'
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        config = {
            "method": "GET",
            "url": "https://<hostname>/api",
            "timeout": 30
        }

        process = HTTPProcess(self.task_id, self.hostname, config, None, self.db)
        process.run_async()

        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()

    @patch('concierge_acpi.HTTPSConnection')
    def test_update_tasks_when_aborted(self, mock_conn_class):
        config = {
            "method": "GET",
            "url": "https://<hostname>/api",
            "timeout": 30
        }

        process = HTTPProcess(self.task_id, self.hostname, config, None, self.db)
        process.aborted = True
        process._update_tasks(success=False, error_msg="Test error")

        task = self.db[self.task_id]
        self.assertEqual(len(task["errors"]), 1)
        self.assertEqual(task["errors"][0]["error"], "Task aborted")


if __name__ == '__main__':
    unittest.main()
