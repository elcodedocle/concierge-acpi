import unittest
from unittest.mock import patch
import sys
import os

from main_utils import recover_dropped_tasks, setup_logging
from persistent_dictionary import OptionallyPersistentOrderedThreadSafeDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

class TestHelperFunctions(unittest.TestCase):
    def test_recover_dropped_tasks(self):
        db = OptionallyPersistentOrderedThreadSafeDict()

        # Add task with running processes
        task_id = "test-123"
        db[task_id] = {
            "task_id": task_id,
            "command": "test",
            "success": [],
            "running": [{"hostname": "server1"}, {"hostname": "server2"}],
            "errors": []
        }

        recover_dropped_tasks(db)

        task = db[task_id]
        self.assertEqual(len(task["running"]), 0)
        self.assertEqual(len(task["errors"]), 2)
        self.assertIn("end_timestamp", task)
        self.assertIn(task_id, db._tagged_for_removal)

    def test_recover_dropped_tasks_empty_db(self):
        db = OptionallyPersistentOrderedThreadSafeDict()
        # Should not raise any exceptions
        recover_dropped_tasks(db)

    def test_recover_dropped_tasks_completed_task(self):
        db = OptionallyPersistentOrderedThreadSafeDict()

        task_id = "test-123"
        db[task_id] = {
            "task_id": task_id,
            "command": "test",
            "success": [{"hostname": "server1"}],
            "running": [],
            "errors": [],
            "end_timestamp": 123456
        }

        recover_dropped_tasks(db)

        # Should not modify completed tasks
        task = db[task_id]
        self.assertEqual(len(task["running"]), 0)
        self.assertEqual(len(task["errors"]), 0)

    @patch('logging.basicConfig')
    def test_setup_logging(self, mock_basic_config):
        setup_logging("DEBUG")
        
        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args[1]
        self.assertEqual(call_kwargs['level'], 10)  # logging.DEBUG = 10

    @patch('logging.basicConfig')
    def test_setup_logging_invalid_level(self, mock_basic_config):
        setup_logging("INVALID")
        
        mock_basic_config.assert_called_once()
        # Should default to INFO
        call_kwargs = mock_basic_config.call_args[1]
        self.assertEqual(call_kwargs['level'], 20)  # logging.INFO = 20


if __name__ == '__main__':
    unittest.main()
