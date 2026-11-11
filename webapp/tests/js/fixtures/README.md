# UI regression fixtures

Minimized, validated records used only by `webapp/tests/test_ui_regressions.py`. They are
engineering test inputs, not research results.

- `transport-failure-incident.json`: a browser incident view derived by the independent
  release audit (`artifacts/release-audit-1793562638949`, finding N1) from real evidence of the
  unchanged `test_wrapper_never_falls_back_to_direct_egress_when_proxy_dies[http]`: ALLOW,
  EXECUTED_FAILED (TRANSPORT_ERROR), no proxy observation, UNVERIFIED with missing-coverage,
  closing-barrier and drain diagnostics. Built with the existing dashboard exporter and
  validated against its Incident schema.
- `missing-observation-lifecycle.json`: the retained lifecycle record of platform run
  `run-20261101-125037-99d0b06f` (Scenario 8), whose observation stage completed with
  `paired: false`. Only the service process ID was removed.

Neither file contains a registered value, key, body or path.
