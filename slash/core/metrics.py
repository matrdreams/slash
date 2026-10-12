"""Minimal Prometheus text exporter. Labels are part of the series key."""

from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self.counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self.gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def _key(self, name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        return name, tuple(sorted((str(k), str(v)) for k, v in labels.items()))

    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        self.counters[self._key(name, labels)] += amount

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        self.gauges[self._key(name, labels)] = value

    def render(self) -> str:
        lines: list[str] = []
        for (name, labels), value in sorted(self.counters.items()):
            lines.append(f"{name}{_fmt_labels(labels)} {value}")
        for (name, labels), value in sorted(self.gauges.items()):
            lines.append(f"{name}{_fmt_labels(labels)} {value}")
        return "\n".join(lines) + ("\n" if lines else "")


def _fmt_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{key}="{value}"' for key, value in labels)
    return "{" + body + "}"
