"""OTA capability reporting; activation must have a separate verified design."""


def status():
    return {'available': False,
            'reason': 'OTA download/activation is not implemented'}
