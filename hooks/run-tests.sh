#!/bin/sh
# Local verification stage for evocode (run by pre-push).
#
# Find a python3 that actually has pytest and run the suite with it. A pytest-less python3
# first on PATH (e.g. an activated ansible/venv) must not spuriously fail the push — but we
# also never "pass" by running a partial subset, so if NO interpreter has pytest we fail
# loudly with how to install it. (The full suite needs pytest: test_root.py / test_swdl.py
# have no self-run entrypoint, so a bare `python3 tests/foo.py` fallback would run nothing
# and falsely pass.)
for py in python3 /usr/bin/python3 python3.11 python3.12 python3.13 /opt/homebrew/bin/python3; do
    command -v "$py" >/dev/null 2>&1 || continue
    "$py" -c 'import pytest' >/dev/null 2>&1 || continue
    echo "evocode tests: $("$py" -c 'import sys; print(sys.executable)')"
    exec "$py" -m pytest tests/ -q
done

echo "evocode tests: no python3 with pytest found (checked PATH + the usual interpreters)." >&2
echo "  install it:  python3 -m pip install pytest    (or: pip install 'evocode[test]')" >&2
exit 1
