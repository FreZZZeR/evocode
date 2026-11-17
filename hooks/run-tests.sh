#!/bin/sh
# Local verification stage for evocode (run by pre-push).
exec python3 -m pytest tests/ -q
