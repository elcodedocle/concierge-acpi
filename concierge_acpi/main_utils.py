# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
import datetime, logging

logger = logging.getLogger("concierge")

def recover_dropped_tasks(db) -> None:
    """Recover tasks that had running processes when the server was restarted"""
    with db.lock:
        for k in db.keys():
            v = db.get(k)
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
                    db[k] = v
                    db.tag_for_removal(k)


def setup_logging(log_level: str) -> None:
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s"
    )