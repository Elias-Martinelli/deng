"""The raw zone behind one interface: PostgreSQL locally, GCS in the cloud."""

from deng.raw_zone.gcs import GcsRawWriter, object_name
from deng.raw_zone.writer import FanOutWriter, RawWriter, open_raw_writer

__all__ = ["FanOutWriter", "GcsRawWriter", "RawWriter", "object_name", "open_raw_writer"]
