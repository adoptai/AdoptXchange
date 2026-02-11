"""Evaluations package for AdoptXchange bulk evaluation functionality."""

# New FIFO Evals Service client (recommended)
from .fifo_client import (
    FIFOEvalsClient,
    run_fifo_evaluation
)

__all__ = [
    # New FIFO client (async job submission)
    'FIFOEvalsClient',
    'run_fifo_evaluation',
]
