from enum import Enum


class OutboundFileStatus(str, Enum):
    """Enum for outbound file processing status."""

    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    FAILED_GENERATION = "FAILED_GENERATION"
    IGNORED = "IGNORED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"

    def __str__(self):
        return self.value

    @classmethod
    def normalize(cls, status):
        if isinstance(status, cls):
            return status.value
        return cls(str(status).upper()).value
