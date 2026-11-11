// Minimized results from the actual v7.2 signed HTTPS dispatch retest.
export const GROUNDING_RETEST = {
  "recorded_on": "2026-11-10",
  "source_sha256": "c2a83e45712ef916794e75aba1faa76af332cccd9316df634823266ebe72a2dc",
  "summary": {
    "cases": 18,
    "accepted_as_expected": [
      "valid_two_cells"
    ],
    "wrongly_accepted": [],
    "attack_receiver_requests": 0
  },
  "results": {
    "valid_two_cells": {
      "unit_check": "ACCEPTED",
      "labels": [
        "SOURCE_DIGEST_MATCH",
        "CELLS_IN_MANDATE",
        "SOURCE_AND_PAYLOAD_BOUND"
      ],
      "dispatch": "SENT",
      "gateway": "ALLOW",
      "receiver_requests": 1
    },
    "wrong_year_same_value": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "year_outside_mandate": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "wrong_metric_same_value": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "metric_outside_mandate": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "wrong_unit": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "wrong_publisher": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "wrong_source_url": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "wrong_workbook_hash": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "incorrect_count": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "count_changed_in_prose_only": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "derived_percentage_added": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "mixed_valid_and_invalid": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "wrong_dataset_digest": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "extra_field": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "duplicate_json_key": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "legacy_v6_prose": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    },
    "false_but_correctly_formatted_cells": {
      "unit_check": "REJECTED",
      "code": "UNGROUNDED_PUBLIC_DATA",
      "dispatch": "REJECTED",
      "dispatch_code": "UNGROUNDED_PUBLIC_DATA",
      "receiver_requests": 0
    }
  }
};
