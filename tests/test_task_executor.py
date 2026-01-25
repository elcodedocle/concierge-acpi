import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from persistent_dictionary import OptionallyPersistentOrderedThreadSafeDict
from task_executor import TaskExecutor

class TestTaskExecutor(unittest.TestCase):
    def setUp(self):
        self.db = OptionallyPersistentOrderedThreadSafeDict()
        self.processes = OptionallyPersistentOrderedThreadSafeDict()
        self.executor = TaskExecutor(self.db, self.processes)
        self.log_callback = MagicMock()

    def test_atomic_task_update(self):
        task_id = "test-task-123"
        self.db[task_id] = {
            "task_id": task_id,
            "command": "test",
            "success": [],
            "running": [{"hostname": "server1"}],
            "errors": []
        }

        self.executor._atomic_task_update(task_id, "success", {"hostname": "server1"})

        task = self.db[task_id]
        self.assertEqual(len(task["success"]), 1)
        self.assertEqual(len(task["running"]), 0)
        self.assertIn("end_timestamp", task)

    def test_create_task(self):
        entries = {
            "server1": ({"command": "ping"}, 30, True),
            "server2": ({"command": "ping"}, 30, True)
        }

        task_id = self.executor.create_task("status", entries)

        self.assertIsNotNone(task_id)
        self.assertIn(task_id, self.db)

        task = self.db[task_id]
        self.assertEqual(task["command"], "status")
        self.assertEqual(len(task["running"]), 2)
        self.assertEqual(len(task["success"]), 0)
        self.assertEqual(len(task["errors"]), 0)
        self.assertIn("start_timestamp", task)
        self.assertIsNone(task.get("execution_plan"))

    def test_create_task_with_execution_plan(self):
        entries = {
            "server1": ({"command": "ping"}, 30, True)
        }

        task_id = self.executor.create_task("deploy_plan", entries, execution_plan="deploy_plan")

        task = self.db[task_id]
        self.assertEqual(task["execution_plan"], "deploy_plan")
        self.assertIn("plan_tasks", task)

    def test_create_task_with_none_command_name(self):
        entries = {
            "server1": ({"mac": "11:22:33:44:55:66"}, -1, False)
        }

        task_id = self.executor.create_task(None, entries)
        task = self.db[task_id]
        self.assertIsNone(task["command"])

    @patch('test_utils.send_wol')
    def test_execute_task_calls_log_callback(self, mock_send_wol):
        entries = {
            "server1": ({"mac": "11:22:33:44:55:66"}, -1, False)
        }

        task_id = self.executor.create_task(None, entries)
        self.executor.execute_task(task_id, "wakeup", entries, None, self.log_callback)

        self.log_callback.assert_called()
        call_args = self.log_callback.call_args[0]
        self.assertEqual(call_args[0], logging.INFO)

    def test_execute_task_with_exception(self):
        entries = {
            "server1": ({"type": "unknown"}, 30, True)
        }

        task_id = self.executor.create_task("test", entries)

        # This should not raise an exception, but log it
        self.executor.execute_task(task_id, "command", entries, None, self.log_callback)

        task = self.db[task_id]
        self.assertEqual(len(task["errors"]), 1)


if __name__ == '__main__':
    unittest.main()
