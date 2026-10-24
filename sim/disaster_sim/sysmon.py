"""Host utilisation for the viewer: CPU, memory and GPU, sampled once a second in the
background (no extra dependencies: /proc and nvidia-smi)."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time


def _cpu_times() -> tuple[float, float]:
    with open("/proc/stat") as f:
        v = [float(x) for x in f.readline().split()[1:]]
    return sum(v), v[3] + v[4]  # total, idle (+iowait)


def _proc_cpu() -> float:
    with open("/proc/self/stat") as f:
        p = f.read().rsplit(")", 1)[1].split()
    return (float(p[11]) + float(p[12])) / os.sysconf("SC_CLK_TCK")  # utime + stime, seconds


def _meminfo() -> tuple[float, float]:
    d = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":")
            d[k] = float(v.split()[0]) / 1048576.0  # GiB
    return d["MemTotal"] - d["MemAvailable"], d["MemTotal"]


class SysMon:
    def __init__(self) -> None:
        self.cores = os.cpu_count() or 1
        self.data = {"cpu": 0.0, "proc_cpu": 0.0, "mem": 0.0, "mem_gb": 0.0, "mem_total_gb": 0.0,
                     "gpu": None, "gpu_mem": None, "cores": self.cores}
        self._smi = shutil.which("nvidia-smi")
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="sysmon", daemon=True).start()

    def _gpu(self) -> tuple[float | None, float | None]:
        if not self._smi:
            return None, None
        try:
            out = subprocess.run([self._smi, "--query-gpu=utilization.gpu,memory.used,memory.total",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2).stdout
            u, mu, mt = [x.strip() for x in out.splitlines()[0].split(",")]
            gpu = float(u)
            mem = float(mu) / float(mt) * 100 if mu.replace(".", "").isdigit() and mt.replace(".", "").isdigit() else None
            return gpu, mem
        except Exception:
            return None, None

    def _run(self) -> None:
        t0, (tot0, idle0), p0 = time.monotonic(), _cpu_times(), _proc_cpu()
        while not self._stop.wait(1.0):
            try:
                t1, (tot1, idle1), p1 = time.monotonic(), _cpu_times(), _proc_cpu()
                used, total = _meminfo()
                gpu, gmem = self._gpu()
                self.data = {
                    "cpu": round(100.0 * (1 - (idle1 - idle0) / max(tot1 - tot0, 1e-9)), 1),  # whole machine
                    "proc_cpu": round(100.0 * (p1 - p0) / max(t1 - t0, 1e-9), 1),  # this server, % of ONE core
                    "mem": round(100.0 * used / total, 1), "mem_gb": round(used, 1), "mem_total_gb": round(total, 1),
                    "gpu": gpu, "gpu_mem": gmem, "cores": self.cores,
                }
                t0, tot0, idle0, p0 = t1, tot1, idle1, p1
            except Exception:
                pass
