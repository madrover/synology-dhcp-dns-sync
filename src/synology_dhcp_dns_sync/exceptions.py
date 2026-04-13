"""Custom exceptions for sync workflows."""


class SyncError(Exception):
    """Base exception for sync failures."""


class ConfigError(SyncError):
    """Raised when configuration is invalid."""


class ZoneValidationError(SyncError):
    """Raised when a live or candidate zone file is invalid."""


class ReloadError(SyncError):
    """Raised when reloading Synology DNS fails."""


class LockHeldError(SyncError):
    """Raised when another sync process already holds the run lock."""
