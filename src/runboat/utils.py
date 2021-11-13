import asyncio
import functools
import re
from concurrent.futures.thread import ThreadPoolExecutor
from functools import wraps
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Generator,
    Iterator,
    ParamSpec,
    TypeVar,
)

_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="sync_to_async")


def slugify(s: str | int) -> str:
    return re.sub(r"[^a-z0-9]", "-", str(s).lower())


# TODO replace ... with P below when mypy supports PEP 612
#      (https://github.com/python/mypy/issues/8645)
P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")


def sync_to_async(func: Callable[..., R]) -> Callable[..., Awaitable[R]]:
    @wraps(func)
    async def inner(*args: Any, **kwargs: Any) -> R:
        f = functools.partial(func, *args, **kwargs)
        return await asyncio.get_running_loop().run_in_executor(_pool, f)

    return inner


def sync_to_async_iterator(
    iterator_func: Callable[..., Generator[R, None, None]]
) -> Callable[..., AsyncGenerator[R, None]]:
    @sync_to_async
    def async_next(iterator: Iterator[R]) -> R:
        try:
            return next(iterator)
        except StopIteration:
            raise StopAsyncIteration()

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
