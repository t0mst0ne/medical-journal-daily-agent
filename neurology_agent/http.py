import json
import os
import urllib.request
from typing import Any, Optional

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class HttpClient:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.scraper = None
        try:
            import cloudscraper

            self.scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "darwin", "mobile": False}
            )
        except ImportError:
            pass

    def _headers(self, headers: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = dict(headers or {})
        if not self.scraper:
            headers.setdefault("User-Agent", BROWSER_UA)
        return headers

    def get_text(self, url: str, headers: Optional[dict[str, str]] = None) -> str:
        headers = self._headers(headers)
        if self.scraper:
            response = self.scraper.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def get_json(self, url: str, headers: Optional[dict[str, str]] = None) -> Any:
        return json.loads(self.get_text(url, headers=headers))

    def get_bytes(self, url: str, headers: Optional[dict[str, str]] = None) -> bytes:
        headers = self._headers(headers)
        if self.scraper:
            response = self.scraper.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.content
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def env_email() -> str:
    return os.getenv("NCBI_EMAIL") or os.getenv("CONTACT_EMAIL") or ""
