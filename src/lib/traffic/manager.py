import asyncio
from contextlib import suppress
from typing import Optional

import structlog

from .async_pool import Pool
from .ran import RanTrafficRouter
from .tti import TTITrafficRouter

logger = structlog.getLogger(__name__)


class PipelineNode:
    def __init__(
        self, fn, fn_args, fn_kwargs, pool_size: int, rx: asyncio.Queue, tx: Optional[asyncio.Queue] = None
    ) -> None:
        self.fn = fn
        self.fn_args = fn_args
        self.fn_kwargs = fn_kwargs

        self.rx = rx
        self.tx = tx
        self._pool = Pool(pool_size)

    async def _handle_item(self, item):
        try:
            result = await self.fn(item, *self.fn_args, **self.fn_kwargs)
        except Exception:
            logger.exception(f"Unhandled exception in {self.fn.__qualname__}")
        else:
            if self.tx:
                await self.tx.put(result)

    async def run(self, stop_event: asyncio.Event):
        while True:
            item = None
            with suppress(asyncio.TimeoutError):
                item = await asyncio.wait_for(self.rx.get(), timeout=0.1)
            if not item:
                if stop_event.is_set():
                    break
                continue

            await self._pool.add(self._handle_item(item))
            self.rx.task_done()
        await self._pool.join()


class Pipeline:
    def __init__(self, source: asyncio.Queue, default_pool_size: int = 64) -> None:
        self._nodes: list[PipelineNode] = []
        self._source: asyncio.Queue = source
        self._default_pool_size = default_pool_size

    def chain(self, method, *args, pool_size: int | None = None, **kwargs):
        chain_len = len(self._nodes)
        pool_size = pool_size if pool_size is not None else self._default_pool_size
        if chain_len == 0:
            self._nodes.append(PipelineNode(method, args, kwargs, pool_size, rx=self._source))
        else:
            prev_tx = asyncio.Queue()  # type: ignore
            self._nodes[-1].tx = prev_tx
            self._nodes.append(PipelineNode(method, args, kwargs, pool_size, rx=prev_tx))
        return self

    async def run(self, stop_event: asyncio.Event):
        tasks = set()
        for node in self._nodes:
            task = asyncio.create_task(node.run(stop_event))
            tasks.add(task)

        await stop_event.wait()
        return await asyncio.gather(*tasks)


class TrafficManager:
    def __init__(self, tti: TTITrafficRouter, ran: RanTrafficRouter) -> None:
        self.tti = tti
        self.ran = ran

    async def run(self, stop_event: asyncio.Event):
        pool_size = 64
        tasks = set()
        # fmt: off
        upstream = (
            Pipeline(self.ran.upstream_rx, default_pool_size=pool_size)
            # This step requires more workers, because of many possible failed MIC challenges
            .chain(self.tti.handle_upstream, pool_size=pool_size * 2)
            .chain(self.ran.handle_upstream_ack_or_reject)
        )
        # fmt: on
        tasks.add(asyncio.create_task(upstream.run(stop_event), name="upstream"))
        logger.info('"ran -[Upstream]-> tti -[UpstreamAck]-> ran" forwarding routine started')

        # fmt: off
        downstream = (
            Pipeline(self.tti.downstream_rx, default_pool_size=pool_size)
            .chain(self.ran.handle_downstream)
        )
        # fmt: on
        tasks.add(asyncio.create_task(downstream.run(stop_event), name="downstream"))
        logger.info('"tti -[Downstream]-> ran" forwarding routine started')

        # fmt: off
        downstream_ack = (
            Pipeline(self.ran.downstream_results_rx, default_pool_size=pool_size)
            .chain(self.tti.handle_downstream_result)
        )
        # fmt: on
        tasks.add(asyncio.create_task(downstream_ack.run(stop_event), name="downstream_result"))
        logger.info('"ran -[DownstreamResult]-> tti" forwarding routine started')

        return await asyncio.gather(*tasks)
