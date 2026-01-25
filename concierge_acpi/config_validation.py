# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

from typing import Any, Dict, List

def validate_config_schema(config_data: Any) -> None:
    if isinstance(config_data, list):
        _validate_hosts_array(config_data)
    elif isinstance(config_data, dict):
        if "hosts" in config_data:
            _validate_hosts_array(config_data["hosts"])
        if "execution_plans" in config_data:
            _validate_execution_plans(config_data["execution_plans"])
    else:
        raise ValueError("Config must be an array or object")


def _validate_hosts_array(hosts: Any) -> None:
    if not isinstance(hosts, list):
        raise ValueError("hosts must be an array")

    for idx, host in enumerate(hosts):
        _validate_host(host, idx)


def _validate_host(host, idx: int):
    if not isinstance(host, dict):
        raise ValueError(f"Host {idx} must be an object")

    if "hostname" not in host:
        raise ValueError(f"Host {idx} missing required field 'hostname'")

    if not isinstance(host["hostname"], str):
        raise ValueError(f"Host {idx} hostname must be a string")

    if "mac" in host:
        if not isinstance(host["mac"], str):
            raise ValueError(f"Host {host['hostname']} mac must be a string")
        mac_clean = host["mac"].replace(":", "").replace("-", "")
        if len(mac_clean) != 12 or not all(c in "0123456789ABCDEFabcdef" for c in mac_clean):
            raise ValueError(f"Host {host['hostname']} has invalid MAC address format")

    if "commands" in host:
        if not isinstance(host["commands"], list):
            raise ValueError(f"Host {host['hostname']} commands must be an array")
        _validate_commands(host["commands"], host["hostname"])


def _validate_commands(commands: List[Any], hostname: str) -> None:
    for idx, cmd in enumerate(commands):
        if not isinstance(cmd, dict):
            raise ValueError(f"Host {hostname} command {idx} must be an object")

        if "name" not in cmd:
            raise ValueError(f"Host {hostname} command {idx} missing 'name'")
        if "type" not in cmd:
            raise ValueError(f"Host {hostname} command {idx} missing 'type'")

        cmd_type = cmd["type"]
        if cmd_type not in ["shell", "http"]:
            raise ValueError(f"Host {hostname} command '{cmd['name']}' has invalid type '{cmd_type}'")

        if cmd_type == "shell":
            _validate_shell_command(cmd, hostname)
        elif cmd_type == "http":
            _validate_http_command(cmd, hostname)


def _validate_shell_command(cmd: Dict[str, Any], hostname: str) -> None:
    if "command" not in cmd:
        raise ValueError(f"Host {hostname} shell command '{cmd['name']}' missing 'command' field")

    if not isinstance(cmd["command"], str):
        raise ValueError(f"Host {hostname} command '{cmd['name']}' command field must be a string")

    has_timeout = "timeout" in cmd
    has_async = "async_timeout" in cmd

    if not has_timeout and not has_async:
        raise ValueError(f"Host {hostname} command '{cmd['name']}' must have 'timeout' or 'async_timeout'")

    if has_timeout and not isinstance(cmd["timeout"], int):
        raise ValueError(f"Host {hostname} command '{cmd['name']}' timeout must be an integer")

    if has_async and not isinstance(cmd["async_timeout"], int):
        raise ValueError(f"Host {hostname} command '{cmd['name']}' async_timeout must be an integer")


def _validate_http_command(cmd: Dict[str, Any], hostname: str) -> None:
    if "url" not in cmd:
        raise ValueError(f"Host {hostname} HTTP command '{cmd['name']}' missing 'url' field")

    if not isinstance(cmd["url"], str):
        raise ValueError(f"Host {hostname} command '{cmd['name']}' url must be a string")

    if "method" in cmd:
        valid_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
        if cmd["method"].upper() not in valid_methods:
            raise ValueError(f"Host {hostname} command '{cmd['name']}' has invalid HTTP method")

    if "payload_placeholder_replacement" in cmd:
        valid_modes = ["disabled", "json_only", "very_unsafe"]
        if cmd["payload_placeholder_replacement"] not in valid_modes:
            raise ValueError(f"Host {hostname} command '{cmd['name']}' has invalid payload_placeholder_replacement")

    if cmd.get("payload_base64_encoded") and cmd.get("payload_placeholder_replacement", "disabled") != "disabled":
        raise ValueError(f"Host {hostname} command '{cmd['name']}' cannot use payload_placeholder_replacement with payload_base64_encoded")

    has_timeout = "timeout" in cmd
    has_async = "async_timeout" in cmd

    if not has_timeout and not has_async:
        raise ValueError(f"Host {hostname} command '{cmd['name']}' must have 'timeout' or 'async_timeout'")


def _validate_execution_plans(plans: Any) -> None:
    if not isinstance(plans, list):
        raise ValueError("execution_plans must be an array")

    plan_names = set()

    for idx, plan in enumerate(plans):
        _validate_execution_plan(idx, plan, plan_names)


def _validate_execution_plan(idx: int, plan, plan_names: set[Any]):
    if not isinstance(plan, dict):
        raise ValueError(f"Execution plan {idx} must be an object")

    if "name" not in plan:
        raise ValueError(f"Execution plan {idx} missing 'name'")

    if not isinstance(plan["name"], str):
        raise ValueError(f"Execution plan {idx} name must be a string")

    plan_name = plan["name"]

    if plan_name in plan_names:
        raise ValueError(f"Duplicate execution plan name '{plan_name}'")
    plan_names.add(plan_name)

    if "tasks" not in plan:
        raise ValueError(f"Execution plan '{plan_name}' missing 'tasks'")

    if not isinstance(plan["tasks"], list):
        raise ValueError(f"Execution plan '{plan_name}' tasks must be an array")

    if "referenced_plans" in plan:
        if not isinstance(plan["referenced_plans"], list):
            raise ValueError(f"Execution plan '{plan_name}' referenced_plans must be an array")

    for task_idx, task in enumerate(plan["tasks"]):
        _validate_task(plan_name, task, task_idx)


def _validate_task(plan_name, task, task_idx: int):
    if not isinstance(task, dict):
        raise ValueError(f"Execution plan '{plan_name}' task {task_idx} must be an object")

    if "command" not in task:
        raise ValueError(f"Execution plan '{plan_name}' task {task_idx} missing 'command'")

    if "hostnames" not in task:
        raise ValueError(f"Execution plan '{plan_name}' task {task_idx} missing 'hostnames'")

    if not isinstance(task["hostnames"], list):
        raise ValueError(f"Execution plan '{plan_name}' task {task_idx} hostnames must be an array")