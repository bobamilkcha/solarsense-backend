class UnknownDeviceError(Exception):
    """Raised when a reading arrives for a device_id with no matching Site."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"No site registered for device_id={device_id!r}")
