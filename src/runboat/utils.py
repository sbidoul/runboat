import asyncio
import re
from concurrent.futures.thread import ThreadPoolExecutor
from functools import wraps

_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="sync_to_async")


def slugify(s: str | int) -> str:
    return re.sub(r"[^a-z0-9]", "-", str(s).lower())


def sync_to_async(func):
    @wraps(func)
    async def inner(*args):
        return await asyncio.get_running_loop().run_in_executor(_pool, func, *args)

    return inner


def sync_to_async_iterator(iterator_func):
    @sync_to_async
    def async_next(iterator):
        try:
            return next(iterator)
        except StopIteration:
            raise StopAsyncIteration()

    @sync_to_async
    def async_iterator_func(*args):
        return iterator_func(*args)

    @wraps(iterator_func)
    async def inner(*args):
        iterator = await async_iterator_func(*args)
        while True:
            try:
                item = await async_next(iterator)
            except StopAsyncIteration:
                return
            else:
                yield item

    return inner
