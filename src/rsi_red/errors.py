import uuid


class ResearchError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def envelope(data=None, error=None):
    return {"schema_version": "1", "request_id": uuid.uuid4().hex,
            "data": data if error is None else None,
            "error": None if error is None else {"code": error.code, "message": str(error),
                                                  "retryable": error.retryable}}


def require(condition, code, message):
    if not condition:
        raise ResearchError(code, message)
