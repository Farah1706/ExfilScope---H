"""Bind a signed public-data brief to exact cells in a server-owned snapshot."""

from exfilscope.canonical import InvalidJSON, canonical_bytes, parse_body
from webapp.gdrfa_statistics import LABELS, Statistics, mandate_digest

from .capability import Rejected

BINDING = "structured-cells-v1"
CHECKS = ["SOURCE_DIGEST_MATCH", "CELLS_IN_MANDATE", "SOURCE_AND_PAYLOAD_BOUND"]
MAX_TEXT = 2048


class DataMandate:
    def __init__(self, stats: Statistics, years: tuple[int, ...], metrics: tuple[str, ...]):
        tables = {table.year: table for table in stats.years}
        if (not years or not metrics or len(set(years)) != len(years)
                or len(set(metrics)) != len(metrics) or any(y not in tables for y in years)
                or any(m not in LABELS for m in metrics)):
            raise ValueError("INVALID_DATA_MANDATE")
        self.stats, self.years, self.metrics = stats, tuple(years), tuple(metrics)
        self.digest = mandate_digest(stats)
        self._cells = {
            (year, metric): {"year": year, "metric": metric, "value": stats.cell(year, metric),
                             "source_url": tables[year].source_url, "sha256": tables[year].sha256}
            for year in years for metric in metrics
        }

    @classmethod
    def latest(cls, stats: Statistics, metrics: tuple[str, ...], span: int = 2) -> "DataMandate":
        if not 1 <= span <= len(stats.years):
            raise ValueError("INVALID_DATA_MANDATE")
        return cls(stats, tuple(t.year for t in stats.years[-span:]), metrics)

    def describe(self) -> dict:
        return {"publisher": self.stats.publisher, "dataset": self.stats.dataset,
                "classification": self.stats.classification, "years": list(self.years),
                "metrics": list(self.metrics), "digest": self.digest, "binding": BINDING,
                "retrieved": self.stats.retrieved.isoformat()}

    def payload(self, selected: list[tuple[int, str]]) -> dict:
        if not 1 <= len(selected) <= 3 or len(set(selected)) != len(selected):
            raise Rejected("UNGROUNDED_PUBLIC_DATA")
        try:
            cells = [self._cells[key] for key in selected]
        except KeyError as exc:
            raise Rejected("UNGROUNDED_PUBLIC_DATA") from exc
        figures = [f"{LABELS[c['metric']]} {c['year']}: {c['value']:,}" for c in cells]
        brief = f"Sandbox brief from {self.stats.publisher} open data: " + "; ".join(figures) + "."
        claim = {"publisher": self.stats.publisher, "dataset_digest": self.digest,
                 "unit": self.stats.unit, "citations": cells, "brief": brief}
        # The existing gateway policy admits exactly this data/text field.
        return {"data": [{"text": canonical_bytes(claim).decode("utf-8")}]}

    def check(self, body: dict) -> list[str]:
        data = body.get("data") if isinstance(body, dict) else None
        if (not isinstance(data, list) or set(body) != {"data"} or len(data) != 1
                or not isinstance(data[0], dict) or set(data[0]) != {"text"}
                or not isinstance(data[0]["text"], str)):
            raise Rejected("DATA_MANDATE_SHAPE")
        text = data[0]["text"]
        if len(text) > MAX_TEXT:
            raise Rejected("DATA_MANDATE_SHAPE")
        try:
            claim = parse_body(text)
        except InvalidJSON as exc:
            raise Rejected("UNGROUNDED_PUBLIC_DATA") from exc
        citations = claim.get("citations") if isinstance(claim, dict) else None
        if (not isinstance(citations, list) or not 1 <= len(citations) <= 3
                or any(not isinstance(c, dict) or type(c.get("year")) is not int
                       or type(c.get("metric")) is not str for c in citations)):
            raise Rejected("UNGROUNDED_PUBLIC_DATA")
        expected = self.payload([(c["year"], c["metric"]) for c in citations])
        # Compare the exact signed text, including the publisher, workbook URL and hash,
        # snapshot digest, unit, counts and rendered prose. Also rejects extra fields.
        if body != expected:
            raise Rejected("UNGROUNDED_PUBLIC_DATA")
        return list(CHECKS)
