"""HEIMDALL backend package.

CRITICAL: pyarrow's default mimalloc allocator segfaults (mi_thread_init) when parquet I/O runs
inside APScheduler worker threads on macOS ARM. Force the system allocator BEFORE anything can
import pyarrow. Verified from macOS crash reports 2026-07-22 (libarrow mi_heap_main SIGSEGV).
"""
import os

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
