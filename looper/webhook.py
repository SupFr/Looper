"""Discord-compatible webhook notifier.

Fire-and-forget on a worker thread so a slow POST can never stall the
detection loop. Any Discord webhook URL works, which is what makes phone
tracking free -- the phone app already exists.
"""

from __future__ import annotations

import threading
import time

import requests

COLOR_START = 0x3BA55D
COLOR_CYCLE = 0x5865F2
COLOR_STOP = 0x747F8D
COLOR_ERROR = 0xED4245


class Webhook:
    def __init__(self, url: str = "", enabled: bool = False) -> None:
        self.url = url
        self.enabled = enabled
        self._started = time.time()

    def configure(self, url: str, enabled: bool) -> None:
        self.url = url.strip()
        self.enabled = enabled

    def mark_start(self) -> None:
        self._started = time.time()

    def _uptime(self) -> str:
        secs = int(time.time() - self._started)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    def send(self, title: str, description: str = "", color: int = COLOR_CYCLE,
             fields: dict[str, str] | None = None) -> None:
        if not self.enabled or not self.url:
            return

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "footer": {"text": f"Looper - up {self._uptime()}"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if fields:
            embed["fields"] = [
                {"name": k, "value": str(v), "inline": True} for k, v in fields.items()
            ]

        payload = {"embeds": [embed]}
        url = self.url

        def _post() -> None:
            try:
                requests.post(url, json=payload, timeout=8)
            except Exception:
                pass   # a dead webhook must never take the loop with it

        threading.Thread(target=_post, daemon=True).start()

    def test(self) -> tuple[bool, str]:
        """Synchronous, for the Test button."""
        if not self.url:
            return False, "No webhook URL set."
        try:
            r = requests.post(self.url, json={
                "embeds": [{
                    "title": "Looper connected",
                    "description": "Notifications are working.",
                    "color": COLOR_START,
                }]
            }, timeout=10)
            if r.status_code in (200, 204):
                return True, "Sent. Check your phone."
            return False, f"HTTP {r.status_code}: {r.text[:180]}"
        except Exception as e:
            return False, str(e)
