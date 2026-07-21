from app.domain import TransportType


class RzdCapabilities:
    supported_transport = [TransportType.TRAIN]
    supports_availability = True
    supports_realtime = False
