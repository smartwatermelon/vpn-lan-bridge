"""Loopback sanity test for scripts/lan-bridge.py.

Starts the proxy as a subprocess in front of a local echo server, with
127.0.0.1 standing in for the LAN IP, and checks that bytes make a round
trip. Touches only loopback sockets; changes no system state.
"""

import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lan-bridge.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def echo_server(listener: socket.socket) -> None:
    while True:
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        with conn:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                conn.sendall(data)


class LoopbackTest(unittest.TestCase):
    def test_version(self):
        out = subprocess.run(
            [sys.executable, str(SCRIPT), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        self.assertIn("1.", out.stdout)

    def test_missing_config_fails(self):
        out = subprocess.run(
            [sys.executable, str(SCRIPT), "--lan-ip", "not-an-ip"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(out.returncode, 0)

    def test_round_trip(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        remote_port = listener.getsockname()[1]
        threading.Thread(target=echo_server, args=(listener,), daemon=True).start()

        proxy_port = free_port()
        proc = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                "--lan-ip",
                "127.0.0.1",
                "--remote-host",
                "127.0.0.1",
                "--remote-port",
                str(remote_port),
                "--proxy-port",
                str(proxy_port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 15
            client = None
            while time.time() < deadline:
                try:
                    client = socket.create_connection(
                        ("127.0.0.1", proxy_port), timeout=5
                    )
                    break
                except OSError:
                    time.sleep(0.2)
            self.assertIsNotNone(client, "proxy never accepted a connection")
            with client:
                client.settimeout(10)
                client.sendall(b"ping-through-bridge")
                got = b""
                while len(got) < len(b"ping-through-bridge"):
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    got += chunk
            self.assertEqual(got, b"ping-through-bridge")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            listener.close()


if __name__ == "__main__":
    unittest.main()
