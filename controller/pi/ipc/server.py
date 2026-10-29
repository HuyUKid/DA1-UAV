"""Local Unix socket server polled by the sole Flight Service thread."""

import errno
import os
from pathlib import Path
import socket
import stat

from ipc.messages import encode, receive_line


class RpcServer:
    """One request per connection; handler runs on the flight main thread."""

    def __init__(self, path, handler):
        self.path = Path(path)
        self.handler = handler
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            if not stat.S_ISSOCK(self.path.stat().st_mode):
                raise RuntimeError(f'IPC path is not a socket: {self.path}')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                try:
                    probe.connect(str(self.path))
                except OSError as error:
                    if error.errno != errno.ECONNREFUSED:
                        raise
                else:
                    raise RuntimeError(f'Another flight service owns IPC socket: {self.path}')
            self.path.unlink()
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.path))
        os.chmod(self.path, 0o660)
        self.socket.listen(8)

    def poll(self, timeout=0.2):
        self.socket.settimeout(timeout)
        try:
            connection, _ = self.socket.accept()
        except socket.timeout:
            return False
        with connection:
            try:
                response = self.handler(receive_line(connection))
                if not isinstance(response, dict):
                    raise TypeError('IPC handler must return a JSON object')
            except Exception as error:
                response = {'ok': False, 'error': str(error),
                            'error_type': type(error).__name__}
            try:
                connection.sendall(encode(response))
            except (BrokenPipeError, ConnectionResetError):
                pass
        return True

    def close(self):
        self.socket.close()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
