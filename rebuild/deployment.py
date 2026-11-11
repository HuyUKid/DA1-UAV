import re


def validate_connection(connection):
    udp = re.fullmatch(r"udpin://127\.0\.0\.1:([0-9]+)", connection)
    if udp:
        port = int(udp[1])
        if 1 <= port <= 65535:
            return connection

    serial = re.fullmatch(r"serial://(/dev/[^:]+):([0-9]+)", connection)
    if serial and int(serial[2]) > 0:
        return connection

    raise ValueError(
        "Dùng udpin://127.0.0.1:PORT hoặc serial:///dev/DEVICE:BAUD"
    )