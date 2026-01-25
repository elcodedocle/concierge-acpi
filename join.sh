#!/usr/bin/env bash
echo '#!/usr/bin/env python3' > concierge-acpi.py
pushd concierge_acpi || exit
cat config_validation.py \
websocket.py \
request_validator.py \
task_scheduler.py \
task_executor_helper.py \
persistent_dictionary.py \
task_executor.py \
configuration.py \
request_handler.py \
main_utils.py \
main.py >> ../concierge-acpi.py
popd || exit
