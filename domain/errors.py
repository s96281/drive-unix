"""Application/domain exceptions."""


class ScanIncompleteError(RuntimeError):
    """Raised when a remote scan cannot guarantee a complete snapshot."""


class SyncConflictError(RuntimeError):
    """Raised when synchronization cannot safely resolve a content conflict."""
