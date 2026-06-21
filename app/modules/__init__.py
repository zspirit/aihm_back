"""Composable business modules (ATS, screening, timesheet, ...).

Each module owns its domain + handlers and subscribes to platform events on
import. It never imports another module directly — only the platform layer
and the event bus. See ADR-05.
"""
