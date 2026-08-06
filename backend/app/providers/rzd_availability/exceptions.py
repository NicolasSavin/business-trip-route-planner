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


class SameStationCodeError(RZDAvailabilityError):
    """Resolution produced the same Express-3 code for different endpoints."""

    def __init__(
        self,
        *,
        origin: str,
        destination: str,
        origin_code: str,
        destination_code: str,
        origin_source: str,
        destination_source: str,
    ):
        super().__init__(
            "Origin and destination resolved to the same Express-3 station code",
            stage="station_resolution",
        )
        self.origin = origin
        self.destination = destination
        self.origin_code = origin_code
        self.destination_code = destination_code
        self.origin_source = origin_source
        self.destination_source = destination_source

    def diagnostic(self) -> dict[str, str]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "origin_code": self.origin_code,
            "destination_code": self.destination_code,
            "origin_source": self.origin_source,
            "destination_source": self.destination_source,
            "stage": "station_resolution",
            "error_type": type(self).__name__,
        }


class RZDNoSeatsError(RZDAvailabilityError):
    """RZD business response 311: no seats for the requested search."""

    error_code = 311

    def __init__(self, message: str):
        super().__init__(message, stage="ticket_search")


class RZDNoTrainError(RZDAvailabilityError):
    """RZD business response 310: no train returned for this date/route."""

    error_code = 310

    def __init__(self, message: str):
        # Keep only the provider's human-readable business message.
        if ":" in message:
            message = message.split(":", 1)[1].strip()
        super().__init__(message, stage="ticket_search")
