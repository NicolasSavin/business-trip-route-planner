from datetime import date

import pytest

from app.domain import TransportType
from app.engine import RouteEngine
from app.providers.gtfs import GTFSLoader, GTFSParser, GTFSProvider

GTFS_DIR = "examples/gtfs"
SERVICE_DAY = date(2026, 8, 11)
REMOVED_SERVICE_DAY = date(2026, 8, 10)
ADDED_SERVICE_DAY = date(2026, 8, 15)


def test_gtfs_loader_reads_required_and_optional_files():
    files = GTFSLoader(GTFS_DIR).load_text_files()
    assert {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt"} <= set(files)


def test_gtfs_parser_builds_internal_models():
    feed = GTFSParser().parse_feed(GTFSLoader(GTFS_DIR).load_text_files())
    assert set(feed.stops) >= {"msk_rail", "kaz_rail", "ekb_rail"}
    assert set(feed.routes) == {"train_msk_ekb", "bus_msk_nnov"}
    assert len(feed.stop_times_by_trip["train_016m_2026"]) == 3


def test_gtfs_provider_maps_consecutive_stop_times_to_transport_segments():
    segments = GTFSProvider(GTFS_DIR).get_segments(SERVICE_DAY, [TransportType.TRAIN, TransportType.BUS])
    assert len(segments) == 4
    first = next(segment for segment in segments if segment.id == "gtfs:train_016m_2026:1:2")
    assert first.provider == "gtfs"
    assert first.origin_city.name == "Москва"
    assert first.destination_city.name == "Казань"
    assert first.transport_type == TransportType.TRAIN
    assert first.vehicle_number == "016М"
    assert first.metadata["gtfs_trip_id"] == "train_016m_2026"


def test_gtfs_provider_filters_transport_types():
    segments = GTFSProvider(GTFS_DIR).get_segments(SERVICE_DAY, [TransportType.BUS])
    assert segments
    assert all(segment.transport_type == TransportType.BUS for segment in segments)


def test_gtfs_calendar_dates_remove_and_add_service():
    provider = GTFSProvider(GTFS_DIR)
    assert provider.get_segments(REMOVED_SERVICE_DAY, [TransportType.TRAIN, TransportType.BUS]) == []
    assert provider.get_segments(ADDED_SERVICE_DAY, [TransportType.TRAIN, TransportType.BUS])


def test_route_engine_works_with_gtfs_provider():
    routes = RouteEngine(GTFSProvider(GTFS_DIR)).search(SERVICE_DAY, "Москва", "Екатеринбург", 1, [TransportType.TRAIN], 1, 30)
    assert len(routes) == 1
    assert routes[0].route.transfers_count == 1
    assert routes[0].route.segments[0].destination_city.name == "Казань"


def test_gtfs_loader_reports_missing_required_files(tmp_path):
    (tmp_path / "stops.txt").write_text("stop_id,stop_name\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="Missing required GTFS files"):
        GTFSLoader(tmp_path).load_text_files()
