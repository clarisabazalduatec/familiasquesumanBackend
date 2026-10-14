from prometheus_client import Counter, Histogram


HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
HTTP_SERVER_ERRORS = Counter(
    "http_server_errors_total",
    "HTTP 5xx responses returned by the API.",
    ("method", "route", "status"),
)
AUTH_EVENTS = Counter(
    "auth_events_total",
    "Authentication and registration attempts.",
    ("action", "outcome"),
)
CHATBOT_REQUESTS = Counter(
    "chatbot_requests_total",
    "Requests sent to the Gemini chatbot.",
    ("outcome",),
)
CHATBOT_REQUEST_DURATION = Histogram(
    "chatbot_request_duration_seconds",
    "Gemini chatbot request duration in seconds.",
)