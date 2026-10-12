"""ADB serial for a device row. An override wins over the loopback port."""


def serial_of(row) -> str:
    override = getattr(row, "adb_serial_override", "") or ""
    if override.strip():
        return override.strip()
    return f"127.0.0.1:{row.adb_port}"
