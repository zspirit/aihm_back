"""Timesheet module — subscribes its handlers to the platform event bus on import."""
from app.modules.timesheet.events import on_candidate_hired
from app.platform.events import event_bus

event_bus.subscribe("ats.candidate.hired", on_candidate_hired)
