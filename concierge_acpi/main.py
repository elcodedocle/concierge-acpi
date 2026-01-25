#!/usr/bin/env python3

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

import logging, os, ssl, threading
from http.server import ThreadingHTTPServer

try:
    from configuration import ConciergeConfig
    from main_utils import recover_dropped_tasks, setup_logging
    from persistent_dictionary import OptionallyPersistentOrderedThreadSafeDict
    from request_handler import Handler
    from task_executor import TaskExecutor
    from task_scheduler import TaskScheduler
    from websocket import WebSocketManager
except ImportError:
    pass

logger = logging.getLogger("concierge")

def main():
    """Main entry point for the application"""
    # Required
    api_key = os.environ.get("CONCIERGE_API_KEY")
    config_path = os.environ.get("CONCIERGE_CONFIG_FILE_PATH")
    cert_file_path = os.environ.get("CONCIERGE_CERT_FILE_PATH", "cert.pem")
    key_file_path = os.environ.get("CONCIERGE_KEY_FILE_PATH", "key.pem")

    # Optional / Default values provisioned
    admin_api_key = os.environ.get("CONCIERGE_ADMIN_API_KEY")
    api_spec_path = os.environ.get("CONCIERGE_API_SPEC_FILE_PATH")
    listening_port = int(os.environ.get("CONCIERGE_LISTENING_PORT", 8443))
    listening_interface = os.environ.get("CONCIERGE_LISTENING_INTERFACE", "0.0.0.0")
    log_level = os.environ.get("CONCIERGE_LOG_LEVEL", "INFO").upper()
    template_path = os.environ.get("CONCIERGE_HTML_TEMPLATE_FILE_PATH", "concierge.html")
    tasks_path = os.environ.get("CONCIERGE_TASKS_FILE_PATH")
    max_tasks = int(os.environ.get("CONCIERGE_MAX_TASKS", 0))

    # WebSocket configuration
    ws_port = int(os.environ.get("CONCIERGE_WS_PORT", 8765))
    ws_interface = os.environ.get("CONCIERGE_WS_INTERFACE", "0.0.0.0")

    if not api_key or not config_path:
        raise RuntimeError("Missing env vars CONCIERGE_API_KEY or CONCIERGE_CONFIG_FILE_PATH")

    setup_logging(log_level)

    config = ConciergeConfig(config_path, template_path, api_spec_path)
    db = OptionallyPersistentOrderedThreadSafeDict(tasks_path, max_tasks)
    processes = OptionallyPersistentOrderedThreadSafeDict(None, max_tasks)

    # Initialize WebSocket manager
    ws_manager = WebSocketManager(
        cert=cert_file_path,
        key=key_file_path,
        secret=api_key,  # Use API key as WebSocket secret
        host=ws_interface,
        port=ws_port,
        token_ttl=30
    )

    task_executor = TaskExecutor(db, processes, ws_manager)

    # Initialize scheduler with execution plans
    scheduler = TaskScheduler(db, processes, task_executor, config.execution_plans, config.hosts)
    task_executor.set_scheduler(scheduler)

    recover_dropped_tasks(db)

    # Set class variables for Handler
    Handler.config = config
    Handler.api_key = api_key
    Handler.admin_api_key = admin_api_key
    Handler.db = db
    Handler.processes = processes
    Handler.task_executor = task_executor
    Handler.ws_manager = ws_manager

    # Start WebSocket server in separate thread
    ws_thread = threading.Thread(target=ws_manager.serve, daemon=True)
    ws_thread.start()

    logger.log(logging.INFO, f"Concierge starting on {listening_interface}:{listening_port}")
    logger.log(logging.INFO, f"WebSocket server on {ws_interface}:{ws_port}")
    logger.log(logging.INFO, f"Log level: {log_level}")
    logger.log(logging.DEBUG, f"Cert file: {cert_file_path}")
    logger.log(logging.DEBUG, f"Key file: {key_file_path}")
    logger.log(logging.DEBUG, f"Open API spec file: {api_spec_path}")
    logger.log(logging.DEBUG, f"HTML template: {template_path}")
    logger.log(logging.DEBUG, f"Tasks persistence file: {tasks_path}")
    logger.log(logging.DEBUG, f"Tasks limit: {max_tasks}")
    logger.log(logging.INFO, f"Loaded {len(config.execution_plans)} execution plans")
    if admin_api_key:
        logger.log(logging.INFO, "Admin API enabled")
    else:
        logger.log(logging.WARNING, "Admin API disabled (CONCIERGE_ADMIN_API_KEY not set)")

    httpd = ThreadingHTTPServer((listening_interface, listening_port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file_path, key_file_path)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.log(logging.INFO, "Shutting down...")
    finally:
        ws_manager.stop()
        logger.log(logging.INFO, "Concierge shut down.")


if __name__ == "__main__":
    main()
