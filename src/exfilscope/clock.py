"""Supervisor-assigned identity for a shared host monotonic clock (never agent input)."""

import os
from uuid import uuid4

from .contracts import Contract, Label


class ClockContext(Contract):
    host_id: Label
    clock_domain_id: Label

    @classmethod
    def local(cls):
        # Without a supervisor configuration, distinct processes deliberately receive
        # distinct domains: wall timestamps must not silently establish correlation.
        return cls(host_id=os.environ.get("EXFILSCOPE_HOST_ID", "LAB_HOST"),
                   clock_domain_id=os.environ.get("EXFILSCOPE_CLOCK_DOMAIN_ID", str(uuid4())))
