#!/usr/bin/env bash
./join.sh
ssh "$CONCIERGE_SERVER" "kill -9 \"\$(ps -C 'python3 concierge-acpi.py' -o pid=)\""
scp concierge_config.json concierge-acpi_swagger-openapi-spec.yml concierge.html concierge-acpi.py "$CONCIERGE_SERVER":~/
ssh "$CONCIERGE_SERVER" "\
CONCIERGE_API_KEY=$CONCIERGE_API_KEY \
CONCIERGE_CONFIG_FILE_PATH=concierge_config.json \
CONCIERGE_CERT_FILE_PATH=cert.pem \
CONCIERGE_KEY_FILE_PATH=key.pem \
CONCIERGE_ADMIN_API_KEY=$CONCIERGE_ADMIN_API_KEY \
CONCIERGE_API_SPEC_FILE_PATH=concierge-acpi_swagger-openapi-spec.yml \
CONCIERGE_TASKS_FILE_PATH=concierge_tasks \
CONCIERGE_MAX_TASKS=100 \
CONCIERGE_LOG_LEVEL=DEBUG \
CONCIERGE_LISTENING_PORT=8443 \
CONCIERGE_LISTENING_INTERFACE=0.0.0.0 \
CONCIERGE_WS_PORT=8765 \
CONCIERGE_WS_INTERFACE=0.0.0.0 \
CONCIERGE_HTML_TEMPLATE_FILE_PATH=concierge.html \
python3 concierge-acpi.py" &
