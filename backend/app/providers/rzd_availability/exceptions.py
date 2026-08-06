class RZDAvailabilityError(RuntimeError):
    """A safe, provider-specific error raised by the RZD adapter."""

    def __init__(
        self, message: str, *, stage: str | None = None, elapsed_ms: float | None = None
    ):
        super().__init__(message)
        self.stage = stage
        self.elapsed_ms = elapsed_ms


class RZDStationNotFound(RZDAvailabilityError):
    pass


class RZDTrainNotFound(RZDAvailabilityError):
    pass
