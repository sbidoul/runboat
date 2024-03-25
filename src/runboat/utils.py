import asyncio
import functools
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Iterator
from concurrent.futures.thread import ThreadPoolExecutor
from functools import wraps
from typing import Any, ParamSpec, TypeVar

_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="sync_to_async")


def slugify(s: str | int) -> str:
    return re.sub(r"[^a-z0-9]", "-", str(s).lower())


P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")


def sync_to_async(func: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    @wraps(func)
    async def inner(*args: Any, **kwargs: Any) -> R:
        f = functools.partial(func, *args, **kwargs)
        return await asyncio.get_running_loop().run_in_executor(_pool, f)

    return inner


def sync_to_async_iterator(
    iterator_func: Callable[P, Generator[R, None, None]],
) -> Callable[P, AsyncGenerator[R, None]]:
    @sync_to_async
    def async_next(iterator: Iterator[R]) -> R:
        try:
            return next(iterator)
        except StopIteration as e:
            raise StopAsyncIteration() from e

    @sync_to_async
    def async_iterator_func(*args: Any, **kwargs: Any) -> Generator[R, None, None]:
        return iterator_func(*args, **kwargs)

    @wraps(iterator_func)
    async def inner(*args: Any, **kwargs: Any) -> AsyncGenerator[R, None]:
        iterator = await async_iterator_func(*args, **kwargs)
        while True:
            try:
                item = await async_next(iterator)
            except StopAsyncIteration:
                return
            else:
                yield item

    return inner
