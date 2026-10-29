"""Small allowlisted runtime configuration; never stores secrets or PX4 params."""
import json
import math
import os
from pathlib import Path


DEFAULTS_PATH = Path(__file__).resolve().parents[1] / 'config' / 'defaults.json'
DEFAULTS = json.loads(DEFAULTS_PATH.read_text())


class RuntimeConfig:
    def __init__(self, path):
        self.path = Path(path)
        self.values = json.loads(json.dumps(DEFAULTS))
        try:
            loaded = json.loads(self.path.read_text())
            self.update(loaded, persist=False)
        except FileNotFoundError:
            pass

    def update(self, changes, persist=True):
        if not isinstance(changes, dict):
            raise ValueError('config changes must be an object')
        unknown = set(changes) - set(DEFAULTS)
        if unknown:
            raise ValueError(f'Unsupported config keys: {sorted(unknown)}')
        updated = json.loads(json.dumps(self.values))
        for key in ('state_interval_s', 'health_interval_s'):
            if key in changes:
                try:
                    value = float(changes[key])
                except (TypeError, ValueError):
                    raise ValueError(f'{key} must be numeric') from None
                low, high = (0.5, 60.0) if key == 'state_interval_s' else (2.0, 300.0)
                if not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f'{key} must be {low}..{high}')
                updated[key] = value
        if persist:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(updated, indent=2) + '\n')
            os.replace(temporary, self.path)
        self.values = updated
        return json.loads(json.dumps(updated))
