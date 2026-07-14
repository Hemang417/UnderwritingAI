import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class InputManifestEntry:
    """One line of a ForecastRun's input_manifest: exactly which DataPoint
    version was read. This is what makes "re-running against unchanged
    inputs reproduces byte-identical output" a checkable claim -- anyone
    auditing a forecast can see precisely which facts fed it.
    """

    data_point_id: uuid.UUID
    field_name: str
    version: int

    def to_dict(self) -> dict:
        return {
            "data_point_id": str(self.data_point_id),
            "field_name": self.field_name,
            "version": self.version,
        }


class InsufficientDataError(Exception):
    """Raised by an engine's pure calculate() function when a required
    input is missing or invalid. The service layer catches this and
    records ForecastRunStatus.INSUFFICIENT_DATA -- a documented, expected
    outcome, not a crash.
    """
