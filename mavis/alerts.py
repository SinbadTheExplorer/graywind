"""Phone alerts for the owner (ntfy).

NOT WIRED YET: notify() does nothing until Task 7 of the cloud-security
plan. Until then lockouts and cap hits reach only audit.log. Callers in
async code must run notify in a thread (it will make a network request).
"""


def notify(title: str, message: str) -> None:
    """Send an alert. Never raises: an alert must not break a request."""
    return None
