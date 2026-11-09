"""
Model transport for loopback HTTP/HTTPS requests.
Uses independent timeouts for connection, header reception, and body idle periods.
No total wall-clock deadline is enforced; each socket read resets the body idle timeout.
"""

import socket
import http.client
import urllib.request
import urllib.error
import json
import time
import ssl
from urllib.parse import urlparse


def complete(request: urllib.request.Request, timeout: float) -> dict:
    """
    Executes a request with granular timeouts and specific retry logic.
    Raises TimeoutError with phase-specific messages or urllib.error.HTTPError.
    """
    parsed = urlparse(request.full_url)
    hostname = parsed.hostname
    if hostname not in ("localhost", "127.0.0.1"):
        raise ValueError(f"Non-loopback host: {hostname}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    retries = 0
    max_retries = 4
    backoff = [1, 2, 4, 8]

    while True:
        conn = None
        headers_received = False
        phase = 'connect'
        try:
            if parsed.scheme == "https":
                conn = http.client.HTTPSConnection(hostname, port, timeout=10)
            else:
                conn = http.client.HTTPConnection(hostname, port, timeout=10)

            try:
                conn.connect()
            except (TimeoutError, socket.timeout):
                raise TimeoutError(f"connect after 10s")

            conn.sock.settimeout(timeout)
            phase = 'response_headers'
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            
            try:
                sock = conn.sock
                sock.settimeout(timeout)
                conn.request(request.get_method(), path, request.data, dict(request.header_items()))
                response = conn.getresponse()
            except (TimeoutError, socket.timeout):
                raise TimeoutError(f"Model response_headers timeout after {timeout}s")
            
            headers_received = True
            status = response.status
            if status >= 400:
                if status in (429, 502, 503, 504) and retries < max_retries:
                    time.sleep(backoff[retries])
                    retries += 1
                    continue
                # Construct compatible HTTPError, keeping the server's error text readable
                import io
                try:
                    error_body = response.read(4096)
                except Exception:
                    error_body = b''
                raise urllib.error.HTTPError(
                    request.full_url, status, response.reason, response.headers, io.BytesIO(error_body)
                )

            sock.settimeout(timeout)
            body = bytearray()
            while True:
                try:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    body.extend(chunk)
                except (TimeoutError, socket.timeout):
                    raise TimeoutError(f"Model response_body_idle timeout after {timeout}s")

            return json.loads(body.decode("utf-8"))

        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError,
                http.client.RemoteDisconnected) as e:
            if not headers_received and retries < max_retries:
                time.sleep(backoff[retries])
                retries += 1
                continue
            raise e
        finally:
            if conn:
                conn.close()
