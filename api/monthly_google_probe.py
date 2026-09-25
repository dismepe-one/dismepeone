"""Read-only source access check for monthly homologation."""

from .monthly_google_reader import monthly_google_reader_info


def google_reader_configured():
    return monthly_google_reader_info() is not None
