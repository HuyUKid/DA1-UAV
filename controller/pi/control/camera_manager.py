"""Camera capability reporting until a camera adapter is installed."""


def status():
    return {'available': False, 'reason': 'No camera adapter is configured'}
