"""Optional node-local GPU measurement; allocation remains a separate scheduler fact."""
import csv
import math
import subprocess
import time


class NvidiaTelemetry:
    def __init__(self, *, runner=subprocess.run, clock=time.time):
        self.runner, self.clock = runner, clock

    def sample(self):
        try:
            response = self.runner(['nvidia-smi',
                '--query-gpu=uuid,index,name,utilization.gpu,memory.used,memory.total,power.draw',
                '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True, timeout=5)
            gpus = []
            for row in csv.reader(response.stdout.splitlines(), skipinitialspace=True):
                if len(row) != 7:
                    raise ValueError('Invalid GPU record')
                def number(value):
                    try:
                        result = float(value)
                        return result if math.isfinite(result) else None
                    except ValueError:
                        return None
                utilization, used, total, power = map(number, row[3:])
                if (utilization is not None and not 0 <= utilization <= 100) or any(
                        value is not None and value < 0 for value in (used, total, power)):
                    raise ValueError('Invalid GPU metric')
                gpus.append({'uuid': row[0].strip(), 'index': int(row[1]), 'name': row[2].strip(),
                             'utilization_percent': utilization, 'memory_used_mib': used,
                             'memory_total_mib': total, 'power_watts': power})
            return {'status': 'available', 'source': 'nvidia-smi', 'scope': 'control-service-node',
                    'sampled_at': self.clock(), 'gpus': gpus}
        except (OSError, subprocess.SubprocessError, ValueError):
            return {'status': 'unavailable', 'source': 'nvidia-smi', 'scope': 'control-service-node',
                    'sampled_at': None, 'gpus': []}
