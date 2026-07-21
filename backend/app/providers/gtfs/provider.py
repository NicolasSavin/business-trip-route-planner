from __future__ import annotations

from datetime import date
from pathlib import Path

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.gtfs.loader import GTFSLoader
from app.providers.gtfs.parser import GTFSParser


class GTFSProvider(TransportProvider):
    provider_name = "gtfs"

    def __init__(self, directory: str | Path, loader: GTFSLoader | None = None, parser: GTFSParser | None = None):
        self.loader = loader or GTFSLoader(directory)
        self.parser = parser or GTFSParser()
        self.feed = self.parser.parse_feed(self.loader.load_text_files())

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType]) -> list[TransportSegment]:
        return self.parser.create_segments(self.feed, departure_date, allowed_transport)
