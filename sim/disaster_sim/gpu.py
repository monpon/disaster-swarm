"""Compute device for the numeric work. The same PyTorch code runs on the GX10's GPU (CUDA)
and, more slowly, on the CPU of a machine without one."""
from __future__ import annotations

import torch

DEV = torch.device("cuda" if torch.cuda.is_available() else "cpu")
ON_GPU = DEV.type == "cuda"


def sync() -> None:
    if ON_GPU:
        torch.cuda.synchronize()
