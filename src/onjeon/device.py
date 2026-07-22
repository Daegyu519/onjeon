"""연산 디바이스 해석 — Apple Silicon은 CUDA 대신 MPS 우선.

torch가 없거나 MPS 미가용이면 cpu. fastembed(ONNX)는 이 대상이 아니다.
"""

from __future__ import annotations


def resolve_device() -> str:
    """'mps'(가용 시) 또는 'cpu'. torch 미설치 환경에서도 안전."""
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
