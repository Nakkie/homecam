from urllib.parse import urlparse


def normalize_rtsp_url(value: str) -> str:
    """Normalize RTSP URLs for go2rtc (requires lowercase rtsp/rtsps scheme)."""
    value = value.strip()
    sep = "://"
    if sep in value:
        scheme, rest = value.split(sep, 1)
        scheme = scheme.lower()
        if scheme in ("rtsp", "rtsps"):
            value = f"{scheme}{sep}{rest}"

    parsed = urlparse(value)
    if parsed.scheme not in ("rtsp", "rtsps"):
        raise ValueError("URL must start with rtsp:// or rtsps://")
    if not parsed.netloc:
        raise ValueError("Invalid RTSP URL")
    return value
