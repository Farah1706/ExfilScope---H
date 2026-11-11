"""Opt-in laboratory full-content capture, never loaded by the deployed monitor.

Only synthetic FAS engineering runs enable this addon. Output belongs to custodian
storage, never routine ledgers. It supplies content, not verification or ground truth.
"""

import json
import os
from pathlib import Path
import time

from exfilscope.config import TRACE_HEADER


class ContentCapture:
    def request(self, flow):
        target = Path(os.environ["EXFILSCOPE_FAS_CONTENT"])
        row = {"trace_id": flow.request.headers.get(TRACE_HEADER),
               "body": flow.request.get_text(strict=True),
               "monotonic": time.monotonic()}
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")


addons = [ContentCapture()]
