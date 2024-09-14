from httpx import Response

class HttpResponseError(Exception):
  def __init__(self, content: str, status_code: int) -> None:
    self.content = content
    self.status_code = status_code