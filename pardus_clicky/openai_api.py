"""Small OpenAI REST client on the standard library (no pip packages needed).

Covers the three calls Clicky makes: Responses (the brain), audio
transcriptions (speech to text) and audio speech (text to speech).
"""

import json
import time
import urllib.error
import urllib.request
import uuid


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class OpenAI:
    def __init__(self, api_key, base_url="https://api.openai.com/v1", timeout=90):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path, body, content_type, timeout=None, retries=1):
        url = f"{self.base_url}/{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": content_type}
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                try:
                    detail = json.loads(detail)["error"]["message"]
                except (ValueError, KeyError, TypeError):
                    detail = detail[:300]
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise ApiError(exc.code, detail) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < retries:
                    time.sleep(1.0)
                    continue
                raise ApiError(0, f"network error: {getattr(exc, 'reason', exc)}") from None
        raise ApiError(0, "unreachable")

    def respond(self, payload, timeout=None):
        raw = self._post("responses", json.dumps(payload).encode("utf-8"), "application/json", timeout)
        return json.loads(raw)

    def transcribe(self, wav, model, language=None, prompt=None):
        boundary = uuid.uuid4().hex
        parts = []

        def field(name, value):
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))

        field("model", model)
        field("response_format", "json")
        if language:
            field("language", language)
        if prompt:
            field("prompt", prompt)
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\n"
            "Content-Type: audio/wav\r\n\r\n".encode("utf-8") + wav + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        raw = self._post("audio/transcriptions", b"".join(parts), f"multipart/form-data; boundary={boundary}", timeout=45)
        return json.loads(raw).get("text", "").strip()

    def speech(self, text, model, voice, instructions=None, fmt="wav"):
        payload = {"model": model, "voice": voice, "input": text, "response_format": fmt}
        if instructions:
            payload["instructions"] = instructions
        return self._post("audio/speech", json.dumps(payload).encode("utf-8"), "application/json", timeout=45)

    def speech_stream(self, text, model, voice, instructions=None, chunk=4800):
        """Yields raw 24 kHz 16-bit mono PCM as it is generated, so playback can start early."""
        payload = {"model": model, "voice": voice, "input": text, "response_format": "pcm"}
        if instructions:
            payload["instructions"] = instructions
        req = urllib.request.Request(f"{self.base_url}/audio/speech", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                                     method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, exc.read().decode("utf-8", "replace")[:300]) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ApiError(0, f"network error: {getattr(exc, 'reason', exc)}") from None
        with resp:
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                yield data
