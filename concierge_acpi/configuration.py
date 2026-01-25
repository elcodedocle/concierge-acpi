# ============================================================================
# CONFIGURATION
# ============================================================================

import json, logging
from typing import Optional

try:
    from config_validation import validate_config_schema
except ImportError:
    pass

logger = logging.getLogger("concierge")


class ConciergeConfig:
    def __init__(self, config_path: str, template_path: str, api_spec_path: Optional[str] = None, validate: bool = True):
        self.config_path = config_path
        self.template_path = template_path
        self.api_spec_path = api_spec_path

        self.process_template_file(True, validate)

        if api_spec_path:
            with open(api_spec_path, "r", encoding="utf-8") as f:
                self.api_spec = f.read()
        else:
            self.api_spec = None

    def _process_config_file(self, config_path: str, validate: bool):
        with open(config_path) as f:
            config_data = json.load(f)

        # Validate config schema
        if validate:
            validate_config_schema(config_data)

        # Separate hosts and execution plans
        if isinstance(config_data, dict):
            self.config = config_data.get("hosts", [])
            self.execution_plans_config = config_data.get("execution_plans", [])
        else:
            # Legacy format - just hosts
            self.config = config_data
            self.execution_plans_config = []

        # Validate HTTP command configurations
        self._validate_http_commands()

        self.hosts = {h["hostname"]: h for h in self.config}

        self.commands = {}
        for h in self.config:
            for c in h.get("commands", []):
                self.commands.setdefault(c["name"], c)

        # Add execution plans as "commands"
        self.execution_plans = {}
        for plan_config in self.execution_plans_config:
            plan_name = plan_config["name"]
            self.execution_plans[plan_name] = plan_config
            self.commands.setdefault(plan_name, {"name": plan_name, "type": "execution_plan"})

    def process_template_file(self, refresh_config: bool = True, validate : bool = True) -> str:
        if refresh_config:
            self._process_config_file(self.config_path, validate)
        host_options = "".join(
            f'<li class="host-row" data-host="{h}" data-commands=\'{json.dumps([cmd["name"] for cmd in self.hosts[h].get("commands", [])])}\'>'
            f'<span><span class="host">{h}</span>'
            f'<div class="seen" id="seen-{h}">last success: —</div></span>'
            f'<span id="status-{h}" class="status">❓</span></li>\n'
            for h in self.hosts
        )
        command_options = "".join(
            f'<option value="{c}">{c}</option>' for c in sorted(self.commands)
        )
        with open(self.template_path, "r", encoding="utf-8") as f:
            self.html_template = f.read()
        self.html = (
            self.html_template
            .replace("{HOST_OPTIONS}", host_options)
            .replace("{COMMAND_OPTIONS}", command_options)
        )
        return self.html

    def _validate_http_commands(self) -> None:
        """Validate HTTP command configurations and log warnings for unsafe features"""
        for host in self.config:
            for cmd in host.get("commands", []):
                if cmd.get("type") == "http":
                    self._validate_http_command(cmd, host)

    @staticmethod
    def _validate_http_command(cmd, host):
        # Check for conflicting configuration
        payload_replacement = cmd.get("payload_placeholder_replacement", "disabled")
        payload_base64 = cmd.get("payload_base64_encoded", False)

        if payload_base64 and payload_replacement != "disabled":
            raise ValueError(
                f"Host '{host['hostname']}', command '{cmd['name']}': "
                f"Cannot use payload_placeholder_replacement with payload_base64_encoded=true. "
                f"Set payload_placeholder_replacement to 'disabled' or set payload_base64_encoded to false."
            )

        # Warn about unsafe payload replacement
        if payload_replacement == "very_unsafe":
            logger.warning(
                f"Host '{host['hostname']}', command '{cmd['name']}': "
                f"Using 'very_unsafe' payload_placeholder_replacement mode. "
                f"This feature can be abused to create virtually any payload. "
                f"Consider using 'json_only' mode for safer operation."
            )
        elif payload_replacement == "json_only":
            logger.info(
                f"Host '{host['hostname']}', command '{cmd['name']}': "
                f"Using 'json_only' payload_placeholder_replacement mode for safer JSON payload generation."
            )