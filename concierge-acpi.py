#!/usr/bin/env python3

# Requires:
#  - python3
#  - HTTPS web server SSL cert and key
#  - A config file (see below for example) and API key (any string)
#
# Optional:
#  - ~/.ssh/config non-interactive credentials provisioning for a ssh user with command privileges for configured hosts
#  - openssl, for server SSL cert generation
#  - curl, for testing
#
# Deploy (see publish-and-redeploy.sh):
# openssl req -x509 -newkey rsa:2048 -nodes \
#  -keyout key.pem -out cert.pem \
#  -days 365 \
#  -subj "/CN=concierge"
# export CONCIERGE_API_KEY=secret
# export CONCIERGE_CONFIG_FILE_PATH=concierge_config.json
# export CONCIERGE_API_SPEC_FILE_PATH=concierge-acpi_swagger-openapi-spec.yml
# export CONCIERGE_LOG_LEVEL=DEBUG
# export CONCIERGE_HTML_TEMPLATE_FILE_PATH=concierge.html
# export CONCIERGE_LISTENING_PORT=8443
# export CONCIERGE_LISTENING_INTERFACE=0.0.0.0
# export CONCIERGE_CERT_FILE_PATH=cert.pem
# export CONCIERGE_KEY_FILE_PATH=key.pem
# export CONCIERGE_TASKS_FILE_PATH=concierge_tasks
# export CONCIERGE_MAX_TASKS=100
# cat << EOF > concierge_config.json
# [
#  {
#    "hostname": "workstation",
#    "mac": "112233445566",
#    "commands": [
#        {
#            "name": "status",
#            "type": "shell",
#            "command": "ping",
#            "arguments": ["-c1", "<hostname>"],
#            "timeout": 30
#        },
#        {
#            "name": "suspend",
#            "type": "shell",
#            "command": "ssh",
#            "arguments": ["<hostname>", "sudo pm-suspend"],
#            "async_timeout": 120
#        }
#    ]
#  }
#]
#EOF
# python3 concierge-acpi.py &
#
# Usage:
# curl -k -X PUT -H "X-API-Key: secret" \
#  https://localhost:8443/concierge/api/v1/wakeup/workstation
# curl -k -X PUT -H "X-API-Key: secret" \
#  https://localhost:8443/concierge/api/v1/commands/suspend/workstation
# (Or point your browser to https://localhost:8443/concierge for the embedded HTML client)

import os, ssl, json, socket, subprocess, logging, threading, shelve, uuid, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import OrderedDict
from subprocess import SubprocessError

# ---- START CONFIG ----

# Required
API_KEY = os.environ.get("CONCIERGE_API_KEY")
CONFIG_PATH = os.environ.get("CONCIERGE_CONFIG_FILE_PATH")
CERT_FILE_PATH = os.environ.get("CONCIERGE_CERT_FILE_PATH", "cert.pem")
KEY_FILE_PATH = os.environ.get("CONCIERGE_KEY_FILE_PATH", "key.pem")

# Optional / Default values provisioned
API_SPEC_PATH = os.environ.get("CONCIERGE_API_SPEC_FILE_PATH")
LISTENING_PORT = int(os.environ.get("CONCIERGE_LISTENING_PORT", 8443))
LISTENING_INTERFACE = os.environ.get("CONCIERGE_LISTENING_INTERFACE", "0.0.0.0")
LOG_LEVEL = os.environ.get("CONCIERGE_LOG_LEVEL", "INFO").upper()
TEMPLATE_PATH = os.environ.get("CONCIERGE_HTML_TEMPLATE_FILE_PATH", "concierge.html")
TASKS_PATH = os.environ.get("CONCIERGE_TASKS_FILE_PATH")
MAX_TASKS = int(os.environ.get("CONCIERGE_MAX_TASKS", 0))

# ---- END CONFIG ----

APPLICATION_JSON = "application/json; charset=utf-8"

with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
    HTML_TEMPLATE = f.read()
if API_SPEC_PATH:
    with open(API_SPEC_PATH, "r", encoding="utf-8") as f:
        API_SPEC = f.read()

if not API_KEY or not CONFIG_PATH:
    raise RuntimeError("Missing env vars CONCIERGE_API_KEY or CONCIERGE_CONFIG_FILE_PATH")

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

HOSTS = {h["hostname"]: h for h in CONFIG}

COMMANDS = {}
for h in CONFIG:
    for c in h.get("commands", []):
        COMMANDS.setdefault(c["name"], c)

HOST_OPTIONS = "".join(
f"""
<li class="host-row" data-host="{h}">
  <span>
    <span class="host">{h}</span>
    <div class="seen" id="seen-{h}">last success: —</div>
  </span>
  <span id="status-{h}" class="status">❓</span>
</li>
""" for h in HOSTS
)

COMMAND_OPTIONS = "".join(
    f'<option value="{c}">{c}</option>' for c in sorted(COMMANDS)
)

HTML = (
    HTML_TEMPLATE
    .replace("{HOST_OPTIONS}", HOST_OPTIONS)
    .replace("{COMMAND_OPTIONS}", COMMAND_OPTIONS)
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger("concierge")

def send_wol(mac):
    mac = mac.replace(":", "").replace("-", "").lower()
    pkt = bytes.fromhex("FF"*6 + mac*16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(pkt, ("255.255.255.255", 9))

class FullDictionaryError(Exception):
    pass

class OptionallyPersistentOrderedThreadSafeDict:
    """
    Thread-safe ordered dictionary with optional persistence and capacity management.
    Uses shelve for persistence, maintains order in separate metadata.
    Survives unexpected restarts.
    Useful for a small serializable collection without high concurrency or frequent updates
    *** not an actual db, not multiprocess safe, the whole thing locks on r/w ***
    """

    def __init__(self, filepath=None, max_size=0):
        self._filepath = filepath
        self._max_size = max_size
        self.lock = threading.RLock()
        if filepath:
            self._metadata_file = f"{filepath}_metadata.json"

        self._load_metadata()

    def _load_metadata(self):
        if self._filepath and os.path.exists(self._metadata_file):
            with open(self._metadata_file, 'r') as fp:
                metadata = json.load(fp)
                self._order = metadata.get('order', [])
                self._tagged_for_removal = OrderedDict((key, None) for key in metadata.get('tagged', []))
        else:
            self._order = []
            self._tagged_for_removal = OrderedDict()

        if self._filepath:
            with shelve.open(self._filepath) as db:
                self._order = [key for key in self._order if key in db]
            self._save_metadata()
        else:
            self._db = OrderedDict()

    def _save_metadata(self):
        if self._metadata_file:
            metadata = {
                'order': self._order,
                'tagged': list(self._tagged_for_removal.keys())
            }
            with open(self._metadata_file, 'w') as fp:
                json.dump(metadata, fp, indent=2)

    def __setitem__(self, key, value):
        with self.lock:
            if self._filepath:
                with shelve.open(self._filepath, writeback=True) as db:
                    self._set_item(db, key, value)
                self._save_metadata()
            else:
                self._set_item(self._db, key, value)

    def _set_item(self, db, key, value):
        if key in db:
            db[key] = value
            self._order.remove(key)
            self._order.append(key)
            self._tagged_for_removal.pop(key, None)
        else:
            if 0 < self._max_size <= len(self._order):
                if not self._tagged_for_removal:
                    raise FullDictionaryError("No entry tagged for removal")

                removal_key, _ = self._tagged_for_removal.popitem(last=False)
                del db[removal_key]
                self._order.remove(removal_key)

            db[key] = value
            self._order.append(key)

    def __getitem__(self, key):
        with self.lock:
            if not self._filepath:
                return self._db[key]
            with shelve.open(self._filepath) as db:
                return db[key]

    def __delitem__(self, key):
        with self.lock:
            if self._filepath:
                with shelve.open(self._filepath, writeback=True) as db:
                    self._del_internal(db, key)
                self._save_metadata()
            else:
                self._del_internal(self._db, key)

    def _del_internal(self, db, key):
        if key in db:
            del db[key]
            self._order.remove(key)
            self._tagged_for_removal.pop(key, None)

    def __len__(self):
        with self.lock:
            return len(self._order)

    def __contains__(self, key):
        with self.lock:
            if key not in self._order:
                return False
            if not self._filepath:
                return key in self._db
            with shelve.open(self._filepath) as db:
                return key in db

    def tag_for_removal(self, key):
        with self.lock:
            if key in self._order and key not in self._tagged_for_removal:
                self._tagged_for_removal[key] = None
                if self._filepath:
                    self._save_metadata()

    def get_oldest_key(self):
        with self.lock:
            if not self._order:
                raise KeyError("Dictionary is empty")
            return self._order[0]

    def get_newest(self):
        with self.lock:
            if not self._order:
                raise KeyError("Dictionary is empty")
            key = self._order[-1]
            if not self._filepath:
                return self._db[key]
            with shelve.open(self._filepath) as db:
                return db[key]

    def get(self, key, default=None):
        with self.lock:
            try:
                if not self._filepath:
                    return self._db.get(key, default)
                with shelve.open(self._filepath) as db:
                    return db.get(key, default)
            except Exception:
                return default

    def keys(self):
        with self.lock:
            return self._order.copy()

    def get_items_reversed(self):
        with self.lock:
            if not self._filepath:
                return [self._db[key] for key in reversed(self._order)]
            with shelve.open(self._filepath) as db:
                return [db[key] for key in reversed(self._order)]

DB = OptionallyPersistentOrderedThreadSafeDict(TASKS_PATH, MAX_TASKS)
PROCESSES = OptionallyPersistentOrderedThreadSafeDict(None, MAX_TASKS)

with DB.lock:
    for k in DB.keys():
        v = DB.get(k)
        if v:
            dropped = v.get("running", [])
            if len(dropped) > 0:
                v["errors"] = v.get("errors", []) + [
                    {**item, "error": "Process dropped during restart"} for item in dropped
                ]
                v["running"] = []
                if "end_timestamp" not in v:
                    v["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
                logger.log(logging.ERROR, f"Found {len(dropped)} dropped processes in task {k}")
                DB[k] = v
                DB.tag_for_removal(k)

class Process:
    def __init__(self, task_id, hostname, command, args):
        self.task_id = task_id
        self.hostname = hostname
        self.command = command
        self.args = args
        self.proc = None
        self.thread = None
        self.aborted = False

    def _update_tasks(self):
        with DB.lock:
            entry = DB.get(self.task_id)
            if entry:
                hostname_dict = {"hostname": self.hostname}
                if self.aborted:
                    entry["errors"].append({
                        "hostname": self.hostname,
                        "error": "Task aborted"
                    })
                elif self.proc.returncode == 0:
                    entry["success"].append(hostname_dict)
                else:
                    entry["errors"].append({
                        "hostname": self.hostname,
                        "error": f"Process exited with code {self.proc.returncode}"
                    })

                if hostname_dict in entry["running"]:
                    entry["running"].remove(hostname_dict)

                if not entry["running"]:
                    if "end_timestamp" not in entry:
                        entry["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
                    DB.tag_for_removal(self.task_id)

                DB[self.task_id] = entry

    def run_async(self, timeout=None):
        def target():
            self.proc = subprocess.Popen(
                [self.command] + self.args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            try:
                if timeout and timeout > 0:
                    self.proc.wait(timeout=timeout)
                else:
                    self.proc.wait()
            except subprocess.TimeoutExpired:
                self._terminate_process()

            self._update_tasks()

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()

    def run_sync(self, timeout=None):
        self.proc = subprocess.Popen(
            [self.command] + self.args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        try:
            if timeout and timeout > 0:
                self.proc.wait(timeout=timeout)
            else:
                self.proc.wait()
        except subprocess.TimeoutExpired:
            self._terminate_process()

    def _terminate_process(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
                except SubprocessError:
                    pass
            except SubprocessError:
                pass

    def abort(self):
        self.aborted = True
        self._terminate_process()


def _atomic_task_update(task_id, field, value):
    with DB.lock:
        task = DB[task_id]
        hostname_dict = {"hostname": value["hostname"]}
        if hostname_dict in task["running"]:
            task["running"].remove(hostname_dict)
        task[field].append(value)
        if not task["running"]:
            if "end_timestamp" not in task:
                task["end_timestamp"] = int(datetime.datetime.now().timestamp() * 1000)
            DB.tag_for_removal(task_id)
        DB[task_id] = task


class RequestParser:
    @staticmethod
    def parse_post_path(path):
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
    def validate_wakeup_host(hostname, host_entry):
        if not host_entry.get("mac"):
            return {"hostname": hostname, "error": "MAC not configured"}
        return None

    @staticmethod
    def validate_command_host(hostname, host_entry, command_name):
        commands = {cmd["name"]: cmd for cmd in host_entry.get("commands", [])}
        cmd = commands.get(command_name)

        if not cmd:
            return {"hostname": hostname, "error": "Command not allowed"}, None

        if cmd["type"] != "shell" or not cmd.get("command"):
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
    def validate_hosts(hosts, action, command_name):
        errors = []
        entries = {}

        for h in hosts:
            host_entry = HOSTS.get(h)
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


class TaskExecutor:
    @staticmethod
    def execute_wakeup(task_id, hostname, entry, log_callback):
        send_wol(entry.get("mac"))
        _atomic_task_update(task_id, "success", {"hostname": hostname})
        log_callback(logging.INFO, "wakeup sent", hostname)

    @staticmethod
    def execute_command_async(task_id, hostname, entry, timeout, log_callback):
        command = entry.get("command")
        args = [arg.replace("<hostname>", hostname) for arg in entry.get("arguments", [])]
        p = Process(task_id, hostname, command, args)
        PROCESSES[task_id][hostname] = p
        p.run_async(timeout if timeout >= 0 else None)
        log_callback(logging.INFO, "command started (async)", hostname)

    @staticmethod
    def execute_command_sync(task_id, hostname, entry, timeout, log_callback):
        command = entry.get("command")
        args = [arg.replace("<hostname>", hostname) for arg in entry.get("arguments", [])]
        p = Process(task_id, hostname, command, args)

        try:
            p.run_sync(timeout if timeout > 0 else None)

            if p.proc.returncode == 0:
                _atomic_task_update(task_id, "success", {"hostname": hostname})
                log_callback(logging.INFO, "command completed (sync)", hostname)
            else:
                _atomic_task_update(task_id, "errors", {
                    "hostname": hostname,
                    "error": f"Exit code {p.proc.returncode}"
                })
                log_callback(logging.INFO, f"command failed (sync) rc={p.proc.returncode}", hostname)
        except subprocess.TimeoutExpired:
            _atomic_task_update(task_id, "errors", {"hostname": hostname, "error": "Timeout"})
            log_callback(logging.INFO, "command timeout (sync)", hostname)

    @staticmethod
    def execute_task(task_id, action, entries, log_callback):
        for hostname, (entry, timeout, is_sync) in entries.items():
            try:
                if action == "wakeup":
                    TaskExecutor.execute_wakeup(task_id, hostname, entry, log_callback)
                elif is_sync:
                    TaskExecutor.execute_command_sync(task_id, hostname, entry, timeout, log_callback)
                else:
                    TaskExecutor.execute_command_async(task_id, hostname, entry, timeout, log_callback)
            except Exception as e:
                _atomic_task_update(task_id, "errors", {"hostname": hostname, "error": str(e)})
                log_callback(logging.INFO, f"action failed ({str(e)})", hostname)
                if logger.isEnabledFor(logging.DEBUG):
                    logging.exception(e)

    @staticmethod
    def create_task(command_name, entries):
        task_id = str(uuid.uuid4())
        task_data = {
            "task_id": task_id,
            "start_timestamp": int(datetime.datetime.now().timestamp() * 1000),
            "command": command_name,
            "success": [],
            "running": [{"hostname": hostname} for hostname in entries.keys()],
            "errors": []
        }
        DB[task_id] = task_data
        PROCESSES[task_id] = {}
        logger.log(logging.DEBUG, f"Created task {task_id}, DB now contains {len(DB)} tasks")
        logger.log(logging.DEBUG, f"Task {task_id} in DB: {task_id in DB}")
        return task_id


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        logger.log(logging.DEBUG, f"GET request path: {self.path}")

        if self.path == "/concierge":
            self.log_host(logging.INFO, "serving /concierge web UI")
            self._send_response(200, HTML, "text/html; charset=utf-8", False)
            return

        if self.path == "/concierge/openapi.yaml" and API_SPEC_PATH:
            self.log_host(logging.INFO, "serving /concierge/openapi.yaml spec")
            self._send_response(200, API_SPEC, "application/yaml; charset=utf-8", False, False)
            return

        if not self._api_path_check() or not self._auth_check():
            return

        if self.path == "/concierge/api/v1/tasks":
            self.log_host(logging.INFO, "serving /concierge/api/v1/tasks")
            task_list = DB.get_items_reversed()
            self._send_response(200, task_list)
            return

        if self.path.startswith("/concierge/api/v1/tasks/"):
            parts = self.path.strip("/").split("/")
            logger.log(logging.DEBUG, f"Path parts: {parts}, len={len(parts)}")
            if len(parts) == 5:
                task_id = parts[4]
                logger.log(logging.DEBUG, f"GET request for task {task_id}")
                logger.log(logging.DEBUG, f"DB contains {len(DB)} tasks")
                logger.log(logging.DEBUG, f"DB keys: {DB.keys()}")
                logger.log(logging.DEBUG, f"Task {task_id} in DB: {task_id in DB}")
                if task_id in DB:
                    self.log_host(logging.INFO, f"serving /concierge/api/v1/tasks/{task_id}")
                    task = DB.get(task_id)
                    self._send_response(200, task)
                    return
                else:
                    self.log_host(logging.DEBUG, f"task {task_id} not found in DB")

        self.log_host(logging.DEBUG, "404 Not found")
        self._send_response(404, {"errors": [{"error": "Not found"}]})

    def _handle_validation_errors(self, errors):
        error_types = ["Host not allowed", "MAC not configured", "Command not allowed"]
        code = 403 if any(e.get("error") in error_types for e in errors) else 500
        log_level = logging.WARNING if code == 500 else logging.INFO

        for err in errors:
            self.log_host(log_level, err["error"], err.get("hostname"))

        self._send_response(code, {"errors": errors})

    def _handle_post_error(self, e, code):
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

            hosts = [single_host] if single_host else self._hosts_from_body()
            if not hosts:
                raise ValueError("No hostnames provided")

            errors, entries = HostValidator.validate_hosts(hosts, action, command_name)

            if errors:
                self._handle_validation_errors(errors)
                return

            task_id = TaskExecutor.create_task(command_name, entries)
            TaskExecutor.execute_task(task_id, action, entries, self.log_host)

            task = DB[task_id]
            response_code = 400 if task["errors"] else 200
            self._send_response(response_code, task)

        except Exception as e:
            self._handle_post_error(e, code)

    def do_PUT(self):
        if not self._api_path_check() or not self._auth_check():
            return

        try:
            parts = self.path.strip("/").split("/")
            if len(parts) == 6 and parts[3] == "tasks" and parts[5] == "abort":
                task_id = parts[4]
                logger.log(logging.DEBUG, f"GET request for task {task_id}")
                logger.log(logging.DEBUG, f"DB contains {len(DB)} tasks")
                logger.log(logging.DEBUG, f"DB keys: {DB.keys()}")
                logger.log(logging.DEBUG, f"Task {task_id} in DB: {task_id in DB}")
                if task_id not in DB:
                    self.log_host(logging.INFO, f"Task {task_id} not found")
                    self._send_response(404, {"errors": [{"error": "Task not found"}]})
                    return

                aborted_count = 0
                with PROCESSES.lock:
                    if task_id in PROCESSES:
                        processes = PROCESSES[task_id]
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
                return

            self.log_host(logging.DEBUG, "404 Not found")
            self._send_response(404, {"errors": [{"error": "Not found"}]})

        except Exception as e:
            self.log_host(logging.ERROR, f"Internal server error on {self.path}")
            self.log_host(logging.DEBUG, str(e))
            if logger.isEnabledFor(logging.DEBUG):
                logging.exception(e)
            self._send_response(500, {"errors": [{"error": str(e)}]})

    def _api_path_check(self):
        logger.log(logging.DEBUG, f"API path check for: {self.path}")
        if not self.path.startswith("/concierge/api/v1/"):
            self.log_host(logging.DEBUG, "404 Not found - invalid API path")
            self._send_response(404, {"errors": [{"error": "Not found"}]})
            return False
        return True

    def _auth_check(self):
        api_key = self.headers.get("X-API-Key")
        logger.log(logging.DEBUG, f"Auth check - has key: {api_key is not None}")
        if api_key != API_KEY:
            self.log_host(logging.DEBUG, "401 Invalid or missing credentials")
            self._send_response(401, {"errors": [{"error": "Invalid or missing credentials"}]})
            return False
        return True

    def _send_response(self, code, content, content_type=APPLICATION_JSON, dumps=True, encode=True):
        logger.log(logging.DEBUG, f"Sending {code} response to {self.client_address[0]}")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        output = json.dumps(content) if dumps else content
        self.wfile.write(output.encode() if encode else output)

    def _hosts_from_body(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        data = json.loads(body)
        return data.get("hostnames", [])

    def log_host(self, level, msg, hostname=None):
        parts = [msg]
        if hostname and (hostname in HOSTS or logger.isEnabledFor(logging.DEBUG)):
            parts.append(f"hostname={hostname}")
        if logger.isEnabledFor(logging.DEBUG):
            src_ip = self.client_address[0]
            parts.append(f"src_ip={src_ip}")
        logger.log(level, " ".join(parts))

    def log_message(self, *_):
        # NOOP
        pass


if __name__ == "__main__":
    logger.log(logging.INFO, f"Concierge starting on {LISTENING_INTERFACE}:{LISTENING_PORT}")
    logger.log(logging.INFO, f"Log level: {LOG_LEVEL}")
    logger.log(logging.DEBUG, f"Cert file: {CERT_FILE_PATH}")
    logger.log(logging.DEBUG, f"Key file: {KEY_FILE_PATH}")
    logger.log(logging.DEBUG, f"Open API spec file: {API_SPEC_PATH}")
    logger.log(logging.DEBUG, f"HTML template: {TEMPLATE_PATH}")
    logger.log(logging.DEBUG, f"Tasks persistence file: {TASKS_PATH}")
    logger.log(logging.DEBUG, f"Tasks limit: {MAX_TASKS}")
    httpd = ThreadingHTTPServer((LISTENING_INTERFACE, LISTENING_PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE_PATH, KEY_FILE_PATH)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.serve_forever()
    logger.log(logging.INFO, "Concierge shut down.")