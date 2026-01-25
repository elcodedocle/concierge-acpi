# ============================================================================
# PROCESS CLASSES WITH STREAMING
# ============================================================================


import os, ssl, json, subprocess, logging, threading, uuid, datetime, base64, struct, select
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlencode, quote
from typing import Dict, Tuple, Optional, Any

try:
    from task_executor_helper import send_wol, replace_placeholders, replace_json_placeholders
except ImportError:
    pass

logger = logging.getLogger("concierge")

class StreamableProcess:
    """Process wrapper with WebSocket streaming support"""
    def __init__(self, task_id, hostname, command, args, db, ws_manager, config):
        self.task_id = task_id
        self.hostname = hostname
        self.command = command
        self.args = args
        self.db = db
        self.ws_manager = ws_manager
        self.config = config
        self.proc = None
        self.thread = None
        self.aborted = False

        # Streaming configuration
        self.socket_raw_mode = config.get("socket_raw_mode", "disabled")
        self.socket_raw_stdin = config.get("socket_raw_stdin", False)

    def _stream_output(self):
        if not self.proc or self.socket_raw_mode == "disabled":
            return

        try:
            import fcntl
            # Set stdout to non-blocking mode for real-time streaming
            if self.proc.stdout:
                fd = self.proc.stdout.fileno()
                fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            if self.socket_raw_mode == "jpeg_stream":
                # JPEG stream mode - frame-based with metadata
                self._stream_binary_frames()
            else:
                # CLI mode - text streaming
                self._stream_text_output()

        except Exception as e:
            logger.error(f"Stream output error: {e}")

    def _stream_text_output(self):
        while self.proc.poll() is None and not self.aborted:
            # select for non-blocking read with short timeout
            if self.proc.stdout:
                readable, _, _ = select.select([self.proc.stdout], [], [], 0.05)

                if self.proc.stdout in readable:
                    try:
                        chunk = self.proc.stdout.read(256)
                        if chunk:
                            msg = json.dumps({
                                "type": "stdout",
                                "data": chunk.decode('utf-8', errors='replace')
                            })
                            self.ws_manager.send_to_client(self.task_id, self.hostname, msg)
                    except IOError:
                        # Non-blocking read with no data available
                        pass

        # Read any remaining output
        if self.proc.stdout and not self.aborted:
            try:
                remaining = self.proc.stdout.read()
                if remaining:
                    msg = json.dumps({
                        "type": "stdout",
                        "data": remaining.decode('utf-8', errors='replace')
                    })
                    self.ws_manager.send_to_client(self.task_id, self.hostname, msg)
            except Exception:
                pass

    def _stream_binary_frames(self):
        frame_buffer = bytearray()

        while self.proc.poll() is None and not self.aborted:
            if self.proc.stdout:
                readable, _, _ = select.select([self.proc.stdout], [], [], 0.05)

                if self.proc.stdout in readable:
                    try:
                        chunk = self.proc.stdout.read(8192)
                        if chunk:
                            frame_buffer.extend(chunk)

                            # Try to extract complete frames
                            # This assumes JPEG/MJPEG format (starts with FFD8, ends with FFD9)
                            while len(frame_buffer) >= 2:
                                # Look for JPEG start marker (FF D8)
                                start_idx = frame_buffer.find(b'\xFF\xD8')

                                if start_idx == -1:
                                    # No frame start found, clear buffer up to last 1 byte
                                    # (in case FF is at the end)
                                    if len(frame_buffer) > 1:
                                        frame_buffer = frame_buffer[-1:]
                                    break

                                # Remove any data before the start marker
                                if start_idx > 0:
                                    frame_buffer = frame_buffer[start_idx:]

                                # Look for JPEG end marker (FF D9)
                                end_idx = frame_buffer.find(b'\xFF\xD9', 2)

                                if end_idx == -1:
                                    # No complete frame yet
                                    break

                                # Extract complete frame (including end marker)
                                frame_data = bytes(frame_buffer[:end_idx + 2])
                                frame_buffer = frame_buffer[end_idx + 2:]

                                # Send frame with metadata header
                                self._send_framed_data(frame_data, 'image/jpeg')

                    except IOError:
                        pass

        # Send any remaining complete frame
        if len(frame_buffer) >= 2:
            start_idx = frame_buffer.find(b'\xFF\xD8')
            if start_idx != -1:
                end_idx = frame_buffer.find(b'\xFF\xD9', start_idx + 2)
                if end_idx != -1:
                    frame_data = bytes(frame_buffer[start_idx:end_idx + 2])
                    self._send_framed_data(frame_data, 'image/jpeg')

    def _send_framed_data(self, data, content_type):
        """Send binary data with a metadata header for proper framing"""
        # Create metadata header: type + length
        # Format: [4 bytes: type length][type string][4 bytes: data length][data]
        type_bytes = content_type.encode('utf-8')
        type_len = len(type_bytes)
        data_len = len(data)

        # Build frame: type_len(4) + type + data_len(4) + data
        frame = struct.pack('>I', type_len) + type_bytes + struct.pack('>I', data_len) + data

        self.ws_manager.send_to_client(self.task_id, self.hostname, frame)

    def run_async(self, timeout=None):
        """Run process asynchronously with streaming"""
        def target():
            stdin_mode = subprocess.PIPE if self.socket_raw_stdin else subprocess.DEVNULL
            stdout_mode = subprocess.PIPE if self.socket_raw_mode != "disabled" else subprocess.DEVNULL
            stderr_mode = subprocess.STDOUT if self.socket_raw_mode == "cli" else subprocess.DEVNULL

            try:
                self.proc = subprocess.Popen(
                    [self.command] + self.args,
                    stdin=stdin_mode,
                    stdout=stdout_mode,
                    stderr=stderr_mode,
                    start_new_session=True,
                    bufsize=0  # Unbuffered for real-time streaming
                )
            except Exception as e:
                logger.error(f"Failed to start process: {e}")
                self._update_task(error=str(e))
                return

            if self.socket_raw_mode != "disabled":
                self.ws_manager.register_process(self.task_id, self.hostname, self.proc)

                stream_thread = threading.Thread(target=self._stream_output, daemon=True)
                stream_thread.start()

            try:
                if timeout and timeout > 0:
                    self.proc.wait(timeout=timeout)
                else:
                    self.proc.wait()
            except subprocess.TimeoutExpired:
                self._terminate()
            except Exception as e:
                logger.error(f"Process wait error: {e}")

            # Cleanup
            self.ws_manager.unregister_process(self.task_id, self.hostname)
            self._update_task()

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()

    def run_sync(self, timeout=None):
        """Run process synchronously (no streaming)"""
        try:
            self.proc = subprocess.Popen(
                [self.command] + self.args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception as e:
            logger.error(f"Failed to start process: {e}")
            return

        try:
            if timeout and timeout > 0:
                self.proc.wait(timeout=timeout)
            else:
                self.proc.wait()
        except subprocess.TimeoutExpired:
            self._terminate()

    def _terminate(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    try:
                        self.proc.wait(timeout=5)
                    except Exception:
                        pass
            except Exception:
                pass

    def _update_task(self, error=None):
        with self.db.lock:
            task = self.db.get(self.task_id)
            if task:
                hostname_dict = {"hostname": self.hostname}

                if error:
                    task["errors"].append({"hostname": self.hostname, "error": error})
                elif self.aborted:
                    task["errors"].append({"hostname": self.hostname, "error": "Aborted"})
                elif self.proc and self.proc.returncode == 0:
                    task["success"].append(hostname_dict)
                elif self.proc:
                    task["errors"].append({
                        "hostname": self.hostname,
                        "error": f"Exit code {self.proc.returncode}"
                    })
                else:
                    task["errors"].append({"hostname": self.hostname, "error": "Process failed to start"})

                if hostname_dict in task["running"]:
                    task["running"].remove(hostname_dict)

                if not task["running"]:
                    if "end_timestamp" not in task:
                        task["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
                    self.db.tag_for_removal(self.task_id)

                self.db[self.task_id] = task

                if self.ws_manager:
                    if self.proc and self.proc.returncode == 0:
                        self.ws_manager.broadcast_status(self.task_id, self.hostname, "success")
                    else:
                        self.ws_manager.broadcast_status(self.task_id, self.hostname, "error")

    def abort(self):
        self.aborted = True
        self._terminate()


class HTTPProcess:
    def __init__(self, task_id: str, hostname: str, config: Dict[str, Any], params: Optional[Dict[str, Any]], db):
        self.task_id = task_id
        self.hostname = hostname
        self.config = config
        self.params = params
        self.db = db
        self.thread = None
        self.aborted = False

    def _update_tasks(self, success: bool, error_msg: Optional[str] = None, output: Optional[str] = None, response_code: Optional[int] = None) -> None:
        with self.db.lock:
            entry = self.db.get(self.task_id)
            if entry:
                hostname_dict = {"hostname": self.hostname}
                if self.aborted:
                    entry["errors"].append({
                        "hostname": self.hostname,
                        "error": "Task aborted"
                    })
                elif success:
                    result = {"hostname": self.hostname}
                    if output is not None:
                        result["output"] = output
                    if response_code is not None:
                        result["response_code"] = response_code
                    entry["success"].append(result)
                else:
                    error_data = {"hostname": self.hostname, "error": error_msg or "Unknown error"}
                    if output is not None:
                        error_data["output"] = output
                    if response_code is not None:
                        error_data["response_code"] = response_code
                    entry["errors"].append(error_data)

                if hostname_dict in entry["running"]:
                    entry["running"].remove(hostname_dict)

                if not entry["running"]:
                    if "end_timestamp" not in entry:
                        entry["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
                    self.db.tag_for_removal(self.task_id)

                self.db[self.task_id] = entry

    def _execute_http(self) -> None:
        try:
            method = self.config.get("method", "GET").upper()
            url = replace_placeholders(self.config.get("url", ""), self.hostname, self.params)

            is_https = url.startswith("https://")
            url_without_scheme = url.replace("https://", "").replace("http://", "")
            parts = url_without_scheme.split("/", 1)
            host = parts[0]
            path = "/" + parts[1] if len(parts) > 1 else "/"

            if "path_params" in self.config:
                for key, value in self.config["path_params"].items():
                    placeholder = f"<{key}>"
                    replacement = replace_placeholders(str(value), self.hostname, self.params)
                    path = path.replace(placeholder, quote(replacement))

            if "query_params" in self.config:
                query_dict = {}
                for key, value in self.config["query_params"].items():
                    query_dict[key] = replace_placeholders(str(value), self.hostname, self.params)
                path += "?" + urlencode(query_dict)

            headers = {}
            if "headers" in self.config:
                for header in self.config["headers"]:
                    key = header.get("key", "")
                    value = replace_placeholders(header.get("value", ""), self.hostname, self.params)
                    if key:
                        headers[key] = value

            payload = None
            if "payload" in self.config and self.config["payload"]:
                payload_replacement_mode = self.config.get("payload_placeholder_replacement", "disabled")

                if self.config.get("payload_base64_encoded", False):
                    payload = base64.b64decode(self.config["payload"])
                elif payload_replacement_mode == "disabled":
                    payload = self.config["payload"].encode('utf-8')
                elif payload_replacement_mode == "very_unsafe":
                    payload = replace_placeholders(self.config["payload"], self.hostname, self.params)
                    payload = payload.encode('utf-8')
                elif payload_replacement_mode == "json_only":
                    payload = replace_json_placeholders(self.config["payload"], self.hostname, self.params)
                    payload = payload.encode('utf-8')
                else:
                    raise ValueError(f"Unknown payload_placeholder_replacement mode: {payload_replacement_mode}")

            timeout = self.config.get("timeout", 30)
            conn_class = HTTPSConnection if is_https else HTTPConnection

            if is_https:
                skip_cert_validation = self.config.get("skip_cert_validation", False)
                if skip_cert_validation:
                    context = ssl._create_unverified_context()
                    conn = conn_class(host, timeout=timeout, context=context)
                else:
                    conn = conn_class(host, timeout=timeout)
            else:
                conn = conn_class(host, timeout=timeout)

            try:
                conn.request(method, path, body=payload, headers=headers)
                response = conn.getresponse()
                response_data = response.read().decode('utf-8', errors='replace')

                success = 200 <= response.status < 300
                self._update_tasks(
                    success=success,
                    error_msg=None if success else f"HTTP {response.status}",
                    output=response_data[:1000] if response_data else None,
                    response_code=response.status
                )
            finally:
                conn.close()

        except Exception as e:
            self._update_tasks(success=False, error_msg=str(e))

    def run_async(self) -> None:
        def target():
            if not self.aborted:
                self._execute_http()

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()

    def run_sync(self) -> None:
        if not self.aborted:
            self._execute_http()

    def abort(self) -> None:
        self.aborted = True

# ============================================================================
# TASK EXECUTOR
# ============================================================================

class TaskExecutor:
    def __init__(self, db, processes, ws_manager=None, scheduler=None):
        self.db = db
        self.processes = processes
        self.ws_manager = ws_manager
        self.scheduler = scheduler

    def set_scheduler(self, scheduler) -> None:
        """Set the scheduler after initialization to avoid circular dependency"""
        self.scheduler = scheduler

    def set_ws_manager(self, ws_manager) -> None:
        self.ws_manager = ws_manager

    def _atomic_task_update(self, task_id: str, field: str, value: Dict[str, Any]) -> None:
        with self.db.lock:
            task = self.db[task_id]
            hostname_dict = {"hostname": value["hostname"]}
            if hostname_dict in task["running"]:
                task["running"].remove(hostname_dict)
            task[field].append(value)
            if not task["running"]:
                if "end_timestamp" not in task:
                    task["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
                self.db.tag_for_removal(task_id)
            self.db[task_id] = task

    def execute_wakeup(self, task_id: str, hostname: str, entry: Dict[str, Any], log_callback) -> None:
        send_wol(entry.get("mac"))
        self._atomic_task_update(task_id, "success", {"hostname": hostname})
        log_callback(logging.INFO, "wakeup sent", hostname)

    def execute_http_async(self, task_id: str, hostname: str, entry: Dict[str, Any], params: Optional[Dict[str, Any]], log_callback) -> None:
        p = HTTPProcess(task_id, hostname, entry, params, self.db)
        self.processes[task_id][hostname] = p
        p.run_async()
        log_callback(logging.INFO, "HTTP request started (async)", hostname)

    def execute_http_sync(self, task_id: str, hostname: str, entry: Dict[str, Any], params: Optional[Dict[str, Any]], log_callback) -> None:
        p = HTTPProcess(task_id, hostname, entry, params, self.db)
        p.run_sync()
        log_callback(logging.INFO, "HTTP request completed (sync)", hostname)

    def execute_shell_async(self, task_id: str, hostname: str, entry: Dict[str, Any], timeout: int, params: Optional[Dict[str, Any]], log_callback) -> None:
        command = entry.get("command")
        args = [replace_placeholders(arg, hostname, params) for arg in entry.get("arguments", [])]
        p = StreamableProcess(task_id, hostname, command, args, self.db, self.ws_manager, entry)
        self.processes[task_id][hostname] = p
        p.run_async(timeout if timeout >= 0 else None)
        log_callback(logging.INFO, "command started (async)", hostname)

    def execute_shell_sync(self, task_id: str, hostname: str, entry: Dict[str, Any], timeout: int, params: Optional[Dict[str, Any]], log_callback) -> None:
        command = entry.get("command")
        args = [replace_placeholders(arg, hostname, params) for arg in entry.get("arguments", [])]
        p = StreamableProcess(task_id, hostname, command, args, self.db, self.ws_manager, entry)

        try:
            p.run_sync(timeout if timeout > 0 else None)

            if p.proc and p.proc.returncode == 0:
                self._atomic_task_update(task_id, "success", {"hostname": hostname})
                log_callback(logging.INFO, "command completed (sync)", hostname)
            elif p.proc:
                self._atomic_task_update(task_id, "errors", {
                    "hostname": hostname,
                    "error": f"Exit code {p.proc.returncode}"
                })
                log_callback(logging.INFO, f"command failed (sync) rc={p.proc.returncode}", hostname)
            else:
                self._atomic_task_update(task_id, "errors", {"hostname": hostname, "error": "Failed to start"})
                log_callback(logging.INFO, "command failed to start (sync)", hostname)
        except subprocess.TimeoutExpired:
            self._atomic_task_update(task_id, "errors", {"hostname": hostname, "error": "Timeout"})
            log_callback(logging.INFO, "command timeout (sync)", hostname)

    def execute_task(self, task_id: str, action: str, entries: Dict[str, Tuple[Dict[str, Any], int, bool]], params: Optional[Dict[str, Any]], log_callback, is_execution_plan: bool = False, plan_name: Optional[str] = None) -> None:
        # If this is an execution plan, delegate to scheduler
        if is_execution_plan and self.scheduler and plan_name:
            self.scheduler.execute_plan(plan_name, task_id, log_callback)
            return

        for hostname, (entry, timeout, is_sync) in entries.items():
            try:
                if action == "wakeup":
                    self.execute_wakeup(task_id, hostname, entry, log_callback)
                else:
                    cmd_type = entry.get("type", "shell")
                    if cmd_type == "http":
                        if is_sync:
                            self.execute_http_sync(task_id, hostname, entry, params, log_callback)
                        else:
                            self.execute_http_async(task_id, hostname, entry, params, log_callback)
                    else:
                        if is_sync:
                            self.execute_shell_sync(task_id, hostname, entry, timeout, params, log_callback)
                        else:
                            self.execute_shell_async(task_id, hostname, entry, timeout, params, log_callback)
            except Exception as e:
                self._atomic_task_update(task_id, "errors", {"hostname": hostname, "error": str(e)})
                log_callback(logging.INFO, f"action failed ({str(e)})", hostname)
                if logger.isEnabledFor(logging.DEBUG):
                    logging.exception(e)

    def create_task(self, command_name: Optional[str], entries: Dict[str, Tuple[Dict[str, Any], int, bool]], execution_plan: Optional[str] = None) -> str:
        task_id = str(uuid.uuid4())
        task_data = {
            "task_id": task_id,
            "start_timestamp": int(datetime.datetime.now().timestamp() * 1000),
            "command": command_name,
            "success": [],
            "running": [{"hostname": hostname} for hostname in entries.keys()],
            "errors": [],
            "execution_plan": execution_plan
        }
        if execution_plan:
            task_data["plan_tasks"] = []
        self.db[task_id] = task_data
        self.processes[task_id] = {}
        logger.log(logging.DEBUG, f"Created task {task_id}")
        return task_id