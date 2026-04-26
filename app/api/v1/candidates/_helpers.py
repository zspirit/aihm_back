import os

MAX_CV_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CV_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_CV_EXTENSIONS = {".pdf", ".doc", ".docx"}

TERMINAL_STATUSES = {"cv_analyzed", "evaluated", "call_done"}
