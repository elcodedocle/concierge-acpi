# ============================================================================
# HTTP REQUEST HANDLER
# ============================================================================
import json, logging, os
from http.server import BaseHTTPRequestHandler
from typing import List, Dict, Optional, Any
from urllib import parse

NOT_FOUND = "Not found"

try:
    from config_validation import validate_config_schema
    from configuration import ConciergeConfig
    from persistent_dictionary import OptionallyPersistentOrderedThreadSafeDict
    from request_validator import RequestParser, HostValidator
    from websocket import WebSocketManager
except ImportError:
    pass

APPLICATION_JSON = "application/json; charset=utf-8"

logger = logging.getLogger("concierge")

class Handler(BaseHTTPRequestHandler):
    config: ConciergeConfig = None
    api_key: Optional[str] = None
    admin_api_key: Optional[str] = None
    db: Optional[OptionallyPersistentOrderedThreadSafeDict] = None
    processes = None
    task_executor = None
    ws_manager: WebSocketManager = None

    def do_GET(self):
        logger.log(logging.DEBUG, f"GET request path: {self.path}")

        if self.path == "/concierge":
            self.log_host(logging.INFO, "serving /concierge web UI")
            self._send_response(200, self.config.process_template_file(), "text/html; charset=utf-8", False)
            return

        if self.path == "/concierge/openapi.yaml" and self.config.api_spec:
            self.log_host(logging.INFO, "serving /concierge/openapi.yaml spec")
            self._send_response(200, self.config.api_spec, "application/yaml; charset=utf-8", False, False)
            return

        if self.path.startswith("/concierge/api/v1/ws/token"):
            self._serve_ws_token()
            return

        if self.path.startswith("/admin/") and self.serve_admin_endpoint():
            return

        if not self._api_path_check() or not self._auth_check():
            return

        if self.path.startswith("/concierge/api/v1/tasks") and self._serve_tasks():
            return

        self.log_host(logging.DEBUG, "404 Not found")
        self._send_response(404, {"errors": [{"error": NOT_FOUND}]})

    def _serve_ws_token(self):
        if not self._api_path_check() or not self._auth_check():
            return

        try:
            query = parse.parse_qs(parse.urlparse(self.path).query)
            task_id = query.get("task_id", [None])[0]
            hostname = query.get("hostname", [None])[0]

            if not task_id or not hostname:
                self._send_response(400, {"errors": [{"error": "Missing task_id or hostname"}]})
                return

            # Get command config to determine streaming mode
            task = self.db.get(task_id)
            if not task:
                self._send_response(404, {"errors": [{"error": "Task not found"}]})
                return

            command_name = task.get("command")
            host_config = self.config.hosts.get(hostname, {})
            commands = {cmd["name"]: cmd for cmd in host_config.get("commands", [])}
            cmd_config = commands.get(command_name, {})

            mode = cmd_config.get("socket_raw_mode", "disabled")

            # Issue token
            token = self.ws_manager.issue_token("api_user", task_id, hostname)

            self.log_host(logging.INFO, f"issued WebSocket token for task {task_id}, host {hostname}")
            self._send_response(200, {
                "token": token,
                "mode": mode,
                "task_id": task_id,
                "hostname": hostname
            })
        except Exception as e:
            logger.error(f"Failed to issue WebSocket token: {e}")
            self._send_response(500, {"errors": [{"error": str(e)}]})
            return

    def _handle_validation_errors(self, errors: List[Dict[str, str]]) -> None:
        error_types = ["Host not allowed", "MAC not configured", "Command not allowed"]
        code = 403 if any(e.get("error") in error_types for e in errors) else 500
        log_level = logging.WARNING if code == 500 else logging.INFO

        for err in errors:
            self.log_host(log_level, err["error"], err.get("hostname"))

        self._send_response(code, {"errors": errors})

    def _handle_post_error(self, e: Exception, code: int) -> None:
        if code == 500 or isinstance(e, Exception) and not isinstance(e, ValueError):
            self.log_host(logging.ERROR, f"Internal server error on {self.path}")
            code = 500

        self.log_host(logging.DEBUG, str(e))

        if logger.isEnabledFor(logging.DEBUG) and not isinstance(e, ValueError):
            logging.exception(e)

        self._send_response(code, {"errors": [{"error": str(e)}]})

    def do_POST(self):
        if not self._api_path_check() or not self._auth_check():
            return

        code = 500

        try:
            action, command_name, single_host = RequestParser.parse_post_path(self.path)
            code = 400

            body_data = self._get_body_data()
            hosts = [single_host] if single_host else body_data.get("hostnames", [])
            params = body_data.get("params")

            if not hosts:
                raise ValueError("No hostnames provided")

            # Check if this is an execution plan
            is_execution_plan = False
            plan_name = None
            if command_name and command_name in self.config.execution_plans:
                is_execution_plan = True
                plan_name = command_name
                # For execution plans, hosts are managed by the plan itself
                entries = {f"plan_{plan_name}": ({}, 0, False)}
            else:
                errors, entries = HostValidator.validate_hosts(hosts, action, command_name, self.config.hosts)

                if errors:
                    self._handle_validation_errors(errors)
                    return

            task_id = self.task_executor.create_task(command_name, entries, execution_plan=plan_name if is_execution_plan else None)
            self.task_executor.execute_task(task_id, action, entries, params, self.log_host, is_execution_plan, plan_name)

            task = self.db.get(task_id)
            response_code = 400 if task["errors"] else 200
            self._send_response(response_code, task)

        except Exception as e:
            self._handle_post_error(e, code)

    def do_PUT(self):
        if self.path.startswith("/admin/"):
            if not self._admin_auth_check():
                return

            if self.path == "/admin/config":
                self._serve_admin_config()
                return

        if not self._api_path_check() or not self._auth_check():
            return

        try:
            parts = self.path.strip("/").split("/")
            if len(parts) == 6 and parts[3] == "tasks" and parts[5] == "abort":
                self._serve_abort(parts)
                return

            self.log_host(logging.DEBUG, "404 Not found")
            self._send_response(404, {"errors": [{"error": NOT_FOUND}]})

        except Exception as e:
            self.log_host(logging.ERROR, f"Internal server error on {self.path}")
            self.log_host(logging.DEBUG, str(e))
            if logger.isEnabledFor(logging.DEBUG):
                logging.exception(e)
            self._send_response(500, {"errors": [{"error": str(e)}]})

    def _serve_abort(self, parts: list[str]):
        task_id = parts[4]
        if task_id not in self.db:
            self.log_host(logging.INFO, f"Task {task_id} not found")
            self._send_response(404, {"errors": [{"error": "Task not found"}]})
            return

        aborted_count = 0
        with self.processes.lock:
            if task_id in self.processes:
                processes = self.processes.get(task_id)
                for hostname, proc in processes.items():
                    proc.abort()
                    aborted_count += 1
                    self.log_host(logging.INFO, f"aborted process for task {task_id}", hostname)

        self.log_host(logging.INFO, f"abort requested for task {task_id}, {aborted_count} processes terminated")
        self._send_response(200, {
            "task_id": task_id,
            "aborted_processes": aborted_count,
            "message": "Task abort initiated"
        })

    def _serve_admin_config(self):
        try:
            body_data = self._get_body_data()

            # Validate new config
            validate_config_schema(body_data)

            # Write atomically
            temp_path = self.config.config_path + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(body_data, f, indent=2)

            os.replace(temp_path, self.config.config_path)

            self.log_host(logging.INFO, "Config updated successfully")
            self._send_response(200, {
                "message": "Config updated successfully. Restart required for changes to take effect."})
            return
        except Exception as e:
            self.log_host(logging.ERROR, f"Failed to update config: {str(e)}")
            self._send_response(400, {"errors": [{"error": f"Config update failed: {str(e)}"}]})
            return

    def _api_path_check(self) -> bool:
        if not self.path.startswith("/concierge/api/v1/"):
            self.log_host(logging.DEBUG, "404 Not found - invalid API path")
            self._send_response(404, {"errors": [{"error": NOT_FOUND}]})
            return False
        return True

    def _auth_check(self) -> bool:
        api_key = self.headers.get("X-API-Key")
        if api_key != self.api_key:
            self.log_host(logging.DEBUG, "401 Invalid or missing credentials")
            self._send_response(401, {"errors": [{"error": "Invalid or missing credentials"}]})
            return False
        return True

    def _admin_auth_check(self) -> bool:
        """Check admin authentication"""
        if not self.admin_api_key:
            self.log_host(logging.WARNING, "Admin endpoint accessed but ADMIN_API_KEY not configured")
            self._send_response(503, {"errors": [{"error": "Admin functionality not configured"}]})
            return False

        admin_key = self.headers.get("X-Admin-Key")
        if admin_key != self.admin_api_key:
            self.log_host(logging.WARNING, "401 Invalid or missing admin credentials")
            self._send_response(401, {"errors": [{"error": "Invalid or missing admin credentials"}]})
            return False
        return True

    def _send_response(self, code: int, content: Any, content_type: str = APPLICATION_JSON, dumps: bool = True, encode: bool = True) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        output = json.dumps(content) if dumps else content
        self.wfile.write(output.encode() if encode else output)

    def _get_body_data(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(body)

    def log_host(self, level: int, msg: str, hostname: Optional[str] = None) -> None:
        parts = [msg]
        if hostname and (hostname in self.config.hosts or logger.isEnabledFor(logging.DEBUG)):
            parts.append(f"hostname={hostname}")
        if logger.isEnabledFor(logging.DEBUG):
            src_ip = self.client_address[0]
            parts.append(f"src_ip={src_ip}")
        logger.log(level, " ".join(parts))

    def log_message(self, *_):
        # NOOP - suppress default logging
        pass

    def serve_admin_endpoint(self):
        if not self._admin_auth_check():
            return True

        if self.path == "/admin/config":
            self.log_host(logging.INFO, "serving /admin/config")
            with open(self.config.config_path, 'r') as f:
                config_data = json.load(f)
            self._send_response(200, config_data)
            return True

        if self.path == "/admin/health":
            self.log_host(logging.INFO, "serving /admin/health")
            health_data = {
                "status": "healthy",
                "tasks_in_db": len(self.db),
                "running_processes": len(self.processes),
                "hosts_count": len(self.config.hosts),
                "execution_plans_count": len(self.config.execution_plans),
                "websocket_clients": len(self.ws_manager.clients) if self.ws_manager else 0
            }
            self._send_response(200, health_data)
            return True

        if self.path == "/admin/stats":
            self.log_host(logging.INFO, "serving /admin/stats")
            all_tasks = self.db.get_items_reversed()
            total_tasks = len(all_tasks)
            completed_tasks = sum(1 for t in all_tasks if t.get("end_timestamp"))
            running_tasks = sum(1 for t in all_tasks if not t.get("end_timestamp"))

            stats_data = {
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "running_tasks": running_tasks,
                "hosts_count": len(self.config.hosts),
                "commands_count": len(self.config.commands),
                "execution_plans_count": len(self.config.execution_plans),
                "websocket_clients": len(self.ws_manager.clients) if self.ws_manager else 0
            }
            self._send_response(200, stats_data)
            return True
        return False

    def _serve_tasks(self):
        if self.path == "/concierge/api/v1/tasks":
            self.log_host(logging.INFO, "serving /concierge/api/v1/tasks")
            task_list = self.db.get_items_reversed()
            self._send_response(200, task_list)
            return True

        if self.path.startswith("/concierge/api/v1/tasks/"):
            parts = self.path.strip("/").split("/")
            if len(parts) == 5:
                task_id = parts[4]
                if task_id in self.db:
                    self.log_host(logging.INFO, f"serving /concierge/api/v1/tasks/{task_id}")
                    task = self.db.get(task_id)
                    self._send_response(200, task)
                    return True
        return False