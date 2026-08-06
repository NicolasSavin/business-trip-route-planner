class RZDAvailabilityError(RuntimeError):
    """A safe, provider-specific error raised by the RZD adapter."""


class RZDStationNotFound(RZDAvailabilityError):
    pass


class RZDTrainNotFound(RZDAvailabilityError):
    pass
