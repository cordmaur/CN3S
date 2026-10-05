"""Multiprocessing helper module"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, wait
from enum import Enum
from functools import partial


class ExecutionType(Enum):
    """Execution type for the parallelism."""

    THREAD = "thread"
    PROCESS = "process"


logger = logging.getLogger(__name__)


class Parallel:
    """Manages a processing pool for parallelism"""

    def __init__(
        self, execution_type: ExecutionType = ExecutionType.THREAD, **kwargs: object
    ) -> None:
        if execution_type == ExecutionType.THREAD:
            self._executor = ThreadPoolExecutor(**kwargs)
        elif execution_type == ExecutionType.PROCESS:
            self._executor = ProcessPoolExecutor(**kwargs)

        else:
            raise ValueError(
                "execution_type arg must be ExecutionType.THREAD or PROCESS",
            )

        self.futures: dict = {}

    def __enter__(self):
        # print(
        #     f"Entering parallel processing with {self._executor._max_workers} workers"
        # )
        return self

    @staticmethod
    def callback(future, function, start_time):
        """Callback used in the timed_submit function to print execution time of the future

        Args:
            future (future): The future being measured
            function (function): The executed function
            start_time (time): Time that the future started

        """
        end_time = time.time()  # Record the end time
        duration = end_time - start_time  # Calculate the duration
        logger.debug("Function %s finished in %.2f seconds", function.__name__, duration)

        return future

    def timed_submit(self, function, *args) -> Future:
        """Start a parallel function and keep track of execution time. It will be printed

        Args:
            function (function): Function to be executed in parallel

        """
        start_time = time.time()  # Record the start time
        future = self._executor.submit(function, *args)
        # wait for the future to finish
        future.add_done_callback(
            partial(Parallel.callback, function=function, start_time=start_time),
        )

        self.futures[future] = function
        return future

    def __exit__(self, exc_type, exc_value, traceback):
        wait(self.futures)

        for future in self.futures.keys():
            if future.exception():
                logger.error("Error in %s", self.futures[future].__name__)
                logger.error("%s", future.exception())

        logger.debug("shutting down the executor")
        self._executor.shutdown()
