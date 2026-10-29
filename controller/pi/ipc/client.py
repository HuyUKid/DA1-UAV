"""Local Unix socket client used by Control Service and diagnostic CLI."""

import socket

from ipc.messages import encode, receive_line


class RpcClient:
    def __init__(self, path, timeout=15.0):
        self.path = str(path)
        self.timeout = timeout

    def request(self, message):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout)
            client.connect(self.path)
            client.sendall(encode(message))
            return receive_line(client)
