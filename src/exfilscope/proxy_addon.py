"""Entry point for mitmdump -s (absolute imports required by addon loader)."""

from exfilscope.monitor import from_env

addons = [from_env()]
