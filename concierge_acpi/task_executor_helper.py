# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

import json, socket
from typing import Any, Dict, Optional

def replace_placeholders(text: str, hostname: str, params: Optional[Dict[str, Any]]) -> str:
    if not isinstance(text, str):
        return text
    result = text.replace("<hostname>", hostname)
    if params:
        for key, value in params.items():
            result = result.replace(f"<{key}>", str(value))
    return result


def replace_json_placeholders(json_text: str, hostname: str, params: Optional[Dict[str, Any]]) -> str:
    """
    Safely replace typed placeholders in JSON text.
    Supports: <string_name>, <number_name>, <boolean_name>, <json_name>, <array_name>
    The resulting JSON must be valid.
    """
    if not isinstance(json_text, str):
        return json_text

    result = json_text
    all_params = {"hostname": hostname}
    if params:
        all_params.update(params)

    for key, value in all_params.items():
        for type_prefix in ["string", "number", "boolean", "json", "array"]:
            placeholder = f"<{type_prefix}_{key}>"
            if placeholder not in result:
                continue

            replacement = None

            if type_prefix == "string":
                # Escape and quote as JSON string
                replacement = json.dumps(str(value))
            elif type_prefix == "number":
                # Validate it's a number
                try:
                    if isinstance(value, bool):
                        raise ValueError("Boolean not allowed for number type")
                    num_val = float(value) if '.' in str(value) else int(value)
                    replacement = json.dumps(num_val)
                except (ValueError, TypeError):
                    raise ValueError(f"Parameter '{key}' cannot be converted to number for {placeholder}")
            elif type_prefix == "boolean":
                if isinstance(value, bool):
                    replacement = json.dumps(value)
                elif str(value).lower() in ["true", "1", "yes"]:
                    replacement = "true"
                elif str(value).lower() in ["false", "0", "no"]:
                    replacement = "false"
                else:
                    raise ValueError(f"Parameter '{key}' cannot be converted to boolean for {placeholder}")
            elif type_prefix == "json":
                # Must be valid JSON object
                try:
                    if isinstance(value, str):
                        parsed = json.loads(value)
                        if not isinstance(parsed, dict):
                            raise ValueError("Must be a JSON object")
                        replacement = value
                    elif isinstance(value, dict):
                        replacement = json.dumps(value)
                    else:
                        raise ValueError("Must be a JSON object")
                except (json.JSONDecodeError, TypeError):
                    raise ValueError(f"Parameter '{key}' is not valid JSON for {placeholder}")
            elif type_prefix == "array":
                # Must be valid JSON array
                try:
                    if isinstance(value, str):
                        parsed = json.loads(value)
                        if not isinstance(parsed, list):
                            raise ValueError("Must be a JSON array")
                        replacement = value
                    elif isinstance(value, list):
                        replacement = json.dumps(value)
                    else:
                        raise ValueError("Must be a JSON array")
                except (json.JSONDecodeError, TypeError):
                    raise ValueError(f"Parameter '{key}' is not valid JSON array for {placeholder}")

            if replacement is not None:
                result = result.replace(placeholder, replacement)

    # Validate final JSON
    try:
        json.loads(result)
    except json.JSONDecodeError as e:
        raise ValueError(f"Resulting payload is not valid JSON after placeholder replacement: {e}")

    return result


def send_wol(mac: str) -> None:
    """Send Wake-on-LAN magic packet"""
    mac = mac.replace(":", "").replace("-", "").lower()
    pkt = bytes.fromhex("FF"*6 + mac*16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(pkt, ("255.255.255.255", 9))