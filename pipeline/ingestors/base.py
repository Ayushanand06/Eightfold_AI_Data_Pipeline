"""Base class that every ingestor must implement."""

from abc import ABC, abstractmethod
from models.canonical import RawRecord


class BaseIngestor(ABC):
    """
    Contract: extract() always returns a RawRecord.
    Missing / malformed input → return a mostly-empty RawRecord, never raise.
    """

    @abstractmethod
    def extract(self) -> RawRecord:
        ...

    def extract_records(self) -> list[RawRecord]:
        """Return one or more candidate records from this source."""
        return [self.extract()]