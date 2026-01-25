# ============================================================================
# REQUEST PARSER AND HOST VALIDATOR
# ============================================================================

from typing import Any, Dict, List, Optional, Tuple

class RequestParser:
    @staticmethod
    def parse_post_path(path: str) -> Tuple[str, Optional[str], Optional[str]]:
        parts = path.strip("/").split("/")
        if len(parts) < 4:
            raise ValueError("Invalid API path")

        if parts[3] == "wakeup" and 4 <= len(parts) <= 5:
            return "wakeup", None, parts[4] if len(parts) == 5 else None
        elif parts[3] == "commands" and 5 <= len(parts) <= 6:
            return "command", parts[4], parts[5] if len(parts) == 6 else None
        else:
            raise ValueError("Invalid API path")


class HostValidator:
    @staticmethod
    def validate_wakeup_host(hostname: str, host_entry: Dict[str, Any]) -> Optional[Dict[str, str]]:
        if not host_entry.get("mac"):
            return {"hostname": hostname, "error": "MAC not configured"}
        return None

    @staticmethod
    def validate_command_host(hostname: str, host_entry: Dict[str, Any], command_name: str) -> Tuple[Optional[Dict[str, str]], Optional[Tuple[Dict[str, Any], int, bool]]]:
        commands = {cmd["name"]: cmd for cmd in host_entry.get("commands", [])}
        cmd = commands.get(command_name)

        if not cmd:
            return {"hostname": hostname, "error": "Command not allowed"}, None

        cmd_type = cmd.get("type", "shell")

        if cmd_type == "http":
            return HostValidator._validate_http_command(cmd, hostname)

        elif cmd_type == "shell":
            return HostValidator._validate_shell_command(cmd, hostname)
        else:
            return {"hostname": hostname, "error": f"Unknown command type: {cmd_type}"}, None

    @staticmethod
    def _validate_shell_command(cmd: Any | None, hostname: str) -> tuple[dict[str, str], None]:
        if not cmd.get("command"):
            return {"hostname": hostname, "error": "Invalid command definition"}, None

        if "timeout" in cmd:
            timeout = cmd["timeout"]
            if not isinstance(timeout, int) or timeout < 0:
                return {"hostname": hostname, "error": "Invalid timeout"}, None
            return None, (cmd, timeout, True)
        elif "async_timeout" in cmd:
            async_timeout = cmd["async_timeout"]
            if not isinstance(async_timeout, int) or async_timeout < -1:
                return {"hostname": hostname, "error": "Invalid async_timeout"}, None
            return None, (cmd, async_timeout, False)
        else:
            return {"hostname": hostname, "error": "Missing timeout or async_timeout"}, None

    @staticmethod
    def _validate_http_command(cmd: Any | None, hostname: str) -> tuple[None, tuple[Any | None, int, bool]]:
        if not cmd.get("url"):
            return {"hostname": hostname, "error": "Invalid HTTP command: missing url"}, None

        timeout = cmd.get("timeout", 30)
        async_timeout = cmd.get("async_timeout")

        if async_timeout is not None:
            if not isinstance(async_timeout, int) or async_timeout < -1:
                return {"hostname": hostname, "error": "Invalid async_timeout"}, None
            return None, (cmd, async_timeout, False)
        else:
            if not isinstance(timeout, int) or timeout < 0:
                return {"hostname": hostname, "error": "Invalid timeout"}, None
            return None, (cmd, timeout, True)

    @staticmethod
    def validate_hosts(hosts: List[str], action: str, command_name: Optional[str], hosts_config: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, str]], Dict[str, Tuple[Dict[str, Any], int, bool]]]:
        errors = []
        entries = {}

        for h in hosts:
            host_entry = hosts_config.get(h)
            if not host_entry:
                errors.append({"hostname": h, "error": "Host not allowed"})
                continue

            if action == "wakeup":
                error = HostValidator.validate_wakeup_host(h, host_entry)
                if error:
                    errors.append(error)
                else:
                    entries[h] = (host_entry, -1, False)
            else:
                error, cmd_data = HostValidator.validate_command_host(h, host_entry, command_name)
                if error:
                    errors.append(error)
                else:
                    entries[h] = cmd_data

        return errors, entries