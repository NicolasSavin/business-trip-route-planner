from __future__ import annotations

from pathlib import Path


class GTFSLoader:
    required_files = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt")
    optional_files = ("calendar_dates.txt",)

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def load_text_files(self) -> dict[str, str]:
        if not self.directory.exists() or not self.directory.is_dir():
            raise FileNotFoundError(f"GTFS directory does not exist: {self.directory}")
        files: dict[str, str] = {}
        missing = [name for name in self.required_files if not (self.directory / name).is_file()]
        if missing:
            raise FileNotFoundError(f"Missing required GTFS files: {', '.join(missing)}")
        for name in (*self.required_files, *self.optional_files):
            path = self.directory / name
            if path.is_file():
                files[name] = path.read_text(encoding="utf-8-sig")
        return files
