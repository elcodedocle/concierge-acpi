# ============================================================================
# EXECUTION PLAN CLASSES
# ============================================================================

import logging, threading, datetime, time
from typing import Dict, List, Optional, Any

try:
    from request_validator import HostValidator
except ImportError:
    pass

class ExecutionPlanTask:
    def __init__(self, command: str, hostnames: List[str], params: Optional[Dict[str, Any]] = None,
                 execute_after: Optional[str] = None, execute_before: Optional[str] = None,
                 if_previous_command: Optional[str] = None, if_previous_command_is: Optional[str] = None,
                 if_previous_command_result: Optional[str] = None, if_previous_output_contains: Optional[str] = None,
                 on_success_jump_to: Optional[str] = None, on_error_jump_to: Optional[str] = None):
        self.command = command
        self.hostnames = hostnames
        self.params = params or {}
        self.execute_after = execute_after
        self.execute_before = execute_before
        self.if_previous_command = if_previous_command
        self.if_previous_command_is = if_previous_command_is
        self.if_previous_command_result = if_previous_command_result
        self.if_previous_output_contains = if_previous_output_contains
        self.on_success_jump_to = on_success_jump_to
        self.on_error_jump_to = on_error_jump_to


class TaskScheduler:

    def __init__(self, db, processes, task_executor, execution_plans: Dict[str, Dict[str, Any]], hosts_config: Dict[str, Dict[str, Any]]):
        self.db = db
        self.processes = processes
        self.task_executor = task_executor
        self.execution_plans = execution_plans
        self.hosts_config = hosts_config
        self.running_plans: Dict[str, threading.Thread] = {}

    def validate_plan(self, plan_name: str) -> None:
        if plan_name not in self.execution_plans:
            raise ValueError(f"Execution plan '{plan_name}' not found")

        plan = self.execution_plans[plan_name]
        for ref_plan in plan.get("referenced_plans", []):
            if ref_plan not in self.execution_plans:
                raise ValueError(f"Referenced execution plan '{ref_plan}' not found")

    def execute_plan(self, plan_name: str, parent_task_id: str, log_callback) -> None:
        def run_plan():
            try:
                self._execute_plan_sync(plan_name, parent_task_id, log_callback)
            except Exception as e:
                log_callback(logging.ERROR, f"Execution plan failed: {str(e)}", None)
                with self.db.lock:
                    task = self.db.get(parent_task_id)
                    if task:
                        task["errors"].append({"error": f"Execution plan error: {str(e)}"})
                        if "end_timestamp" not in task:
                            task["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
                        self.db[parent_task_id] = task

        thread = threading.Thread(target=run_plan, daemon=True)
        self.running_plans[parent_task_id] = thread
        thread.start()

    def _execute_plan_sync(self, plan_name: str, parent_task_id: str, log_callback) -> None:
        self.validate_plan(plan_name)
        plan = self.execution_plans[plan_name]

        execution_sequence = self._build_execution_sequence(plan)

        task_results: Dict[int, Dict[str, Any]] = {}
        idx = 0

        while idx < len(execution_sequence):
            task_info = execution_sequence[idx]
            task_type = task_info["type"]  # "task" or "plan"

            if task_type == "plan":
                ref_plan_name = task_info["plan_name"]
                self._execute_plan_sync(ref_plan_name, parent_task_id, log_callback)
                idx += 1
                continue

            plan_task = task_info["task"]
            task_idx = task_info["original_index"]

            self._update_plan_task_status(parent_task_id, task_idx, "scheduled")

            # Check dependencies
            if not self._check_conditions(plan_task, task_results, task_idx):
                log_callback(logging.INFO, f"Skipping plan task {task_idx} due to unmet conditions", None)
                self._update_plan_task_status(parent_task_id, task_idx, "skipped")
                idx += 1
                continue

            # Nasty wait; completed tasks should trigger any attached execute after instead
            if "execute_after" in plan_task and plan_task["execute_after"] is not None:
                dep_idx = int(plan_task["execute_after"])
                while dep_idx not in task_results:
                    time.sleep(0.1)

            self._update_plan_task_status(parent_task_id, task_idx, "waiting")

            result = self._execute_plan_task(plan_task, parent_task_id, task_idx, log_callback)
            task_results[task_idx] = result

            self._update_parent_task_progress(parent_task_id)

            has_errors = len(result.get("errors", [])) > 0
            has_success = len(result.get("success", [])) > 0

            next_idx = idx + 1  # Default: next task

            if has_errors and not has_success and plan_task.get("on_error_jump_to") is not None:
                # All failed - jump on error
                jump_to = int(plan_task["on_error_jump_to"])
                log_callback(logging.INFO, f"Task {task_idx} failed, jumping to task {jump_to}", None)
                next_idx = self._find_task_index_in_sequence(execution_sequence, jump_to)
            elif has_success and plan_task.get("on_success_jump_to") is not None:
                # At least one success - jump on success
                jump_to = int(plan_task["on_success_jump_to"])
                log_callback(logging.INFO, f"Task {task_idx} succeeded, jumping to task {jump_to}", None)
                next_idx = self._find_task_index_in_sequence(execution_sequence, jump_to)

            idx = next_idx

        with self.db.lock:
            task = self.db.get(parent_task_id)
            if task and not task.get("running"):
                if "end_timestamp" not in task:
                    task["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
                self.db.tag_for_removal(parent_task_id)
                self.db[parent_task_id] = task

    @staticmethod
    def _build_execution_sequence(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        sequence = []
        tasks = plan.get("tasks", [])
        referenced_plans = plan.get("referenced_plans", [])

        has_position_hints = any("execute_at_position" in task for task in tasks)

        if not has_position_hints:
            # Legacy: Referenced plans first
            for ref_plan in referenced_plans:
                sequence.append({"type": "plan", "plan_name": ref_plan})

            for idx, task in enumerate(tasks):
                sequence.append({
                    "type": "task",
                    "task": task,
                    "original_index": idx
                })
        else:
            # Interleaved: sort by position
            all_items = []

            for ref_plan in referenced_plans:
                all_items.append({
                    "type": "plan",
                    "plan_name": ref_plan,
                    "position": 0 # Default to beginning
                })

            for idx, task in enumerate(tasks):
                position = task.get("execute_at_position", idx + len(referenced_plans))
                all_items.append({
                    "type": "task",
                    "task": task,
                    "original_index": idx,
                    "position": position
                })

            all_items.sort(key=lambda x: x["position"])
            sequence = all_items

        return sequence

    @staticmethod
    def _find_task_index_in_sequence(sequence: List[Dict[str, Any]], original_task_idx: int) -> int:
        for i, item in enumerate(sequence):
            if item["type"] == "task" and item["original_index"] == original_task_idx:
                return i
        return len(sequence)

    @staticmethod
    def _check_conditions(plan_task: Dict[str, Any], task_results: Dict[int, Dict[str, Any]], current_idx: int) -> bool:
        if "if_previous_command" in plan_task and plan_task["if_previous_command"] is not None:
            prev_idx = int(plan_task["if_previous_command"])

            if prev_idx >= current_idx or prev_idx not in task_results:
                return False

            prev_result = task_results[prev_idx]

            if "if_previous_command_result" in plan_task and plan_task["if_previous_command_result"]:
                condition = plan_task["if_previous_command_result"]
                if condition == "all_success" and len(prev_result.get("errors", [])) > 0 \
                    or condition == "any_success" and len(prev_result.get("success", [])) == 0 \
                    or condition == "all_error" and len(prev_result.get("success", [])) > 0 \
                    or condition == "any_error" and len(prev_result.get("errors", [])) == 0:
                    return False

            if "if_previous_output_contains" in plan_task and plan_task["if_previous_output_contains"]:
                search_str = plan_task["if_previous_output_contains"]
                all_outputs = []
                for item in prev_result.get("success", []):
                    if "output" in item:
                        all_outputs.append(item["output"])
                for item in prev_result.get("errors", []):
                    if "output" in item:
                        all_outputs.append(item["output"])

                combined_output = "\n".join(all_outputs)
                if search_str not in combined_output:
                    return False

        return True

    def _execute_plan_task(self, plan_task: Dict[str, Any], parent_task_id: str, task_idx: int, log_callback) -> Dict[str, Any]:
        command_name = plan_task["command"]
        hostnames = plan_task.get("hostnames", [])
        params = plan_task.get("params", {})

        if command_name in self.execution_plans:
            self._execute_plan_sync(command_name, parent_task_id, log_callback)
            return {"success": [], "errors": [], "running": []}

        errors, entries = HostValidator.validate_hosts(hostnames, "command", command_name, self.hosts_config)

        if errors:
            return {
                "success": [],
                "errors": errors,
                "running": []
            }

        sub_task_id = f"{parent_task_id}::task{task_idx}"

        task_data = {
            "task_id": sub_task_id,
            "start_timestamp": int(datetime.datetime.now().timestamp() * 1000),
            "command": command_name,
            "success": [],
            "running": [{"hostname": h} for h in hostnames],
            "errors": []
        }
        self.db[sub_task_id] = task_data
        self.processes[sub_task_id] = {}

        self.task_executor.execute_task(sub_task_id, "command", entries, params, log_callback)

        max_wait = 300  # 5 minutes
        waited = 0
        while waited < max_wait:
            task = self.db.get(sub_task_id)
            if task and len(task.get("running", [])) == 0:
                break
            time.sleep(0.5)
            waited += 0.5

        task = self.db.get(sub_task_id)
        result = {
            "success": task.get("success", []),
            "errors": task.get("errors", []),
            "running": task.get("running", [])
        }

        self._update_plan_task_status(parent_task_id, task_idx, "completed")

        return result

    def _update_plan_task_status(self, parent_task_id: str, task_idx: int, status: str) -> None:
        with self.db.lock:
            task = self.db.get(parent_task_id)
            if task:
                if "plan_tasks" not in task:
                    task["plan_tasks"] = {}
                task["plan_tasks"][str(task_idx)] = {
                    "status": status,
                    "timestamp": int(datetime.datetime.now().timestamp() * 1000)
                }
                self.db[parent_task_id] = task

    def _update_parent_task_progress(self, parent_task_id: str) -> None:
        with self.db.lock:
            task = self.db.get(parent_task_id)
            if task:
                plan_tasks = task.get("plan_tasks", {})
                completed = sum(1 for pt in plan_tasks.values() if pt.get("status") == "completed")
                total = len(plan_tasks)

                task["running"] = [{"hostname": f"Plan progress: {completed}/{total}"}]
                self.db[parent_task_id] = task

