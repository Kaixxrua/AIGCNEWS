class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.expirations: dict[str, int] = {}
        self.calls: list[tuple[object, ...]] = []

    async def get(self, key: str):
        self.calls.append(("get", key))
        return self.values.get(key)

    async def set(self, key: str, value: object, *, ex: int | None = None):
        self.calls.append(("set", key, value, ex))
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def delete(self, *keys: str):
        self.calls.append(("delete", *keys))
        for key in keys:
            self.values.pop(key, None)
            self.expirations.pop(key, None)

    async def incr(self, key: str) -> int:
        self.calls.append(("incr", key))
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    async def expire(self, key: str, seconds: int):
        self.calls.append(("expire", key, seconds))
        self.expirations[key] = seconds

    async def ttl(self, key: str) -> int:
        self.calls.append(("ttl", key))
        if key not in self.values:
            return -2
        # 未记剩余时间语义，存在到期时间即返回配置值（恒 > 0）
        return self.expirations.get(key, -1)


    async def eval(self, script, numkeys, *args):
        from backend.app.services.email.otp_store import _STORE_SCRIPT
        first, second = args[:numkeys]
        argv = args[numkeys:]
        if script == _STORE_SCRIPT:
            if await self.get(second) is not None:
                return 0
            await self.set(first, argv[0], ex=argv[1])
            await self.set(second, "1", ex=argv[2])
            return 1
        current = self.values.get(first)
        if isinstance(current, bytes):
            current = current.decode()
        if current != argv[0]:
            return 0
        if argv[1]:
            if argv[2]:
                await self.delete(first, second)
            return 1
        attempts = await self.incr(second)
        if attempts == 1:
            await self.expire(second, argv[3])
        if attempts >= argv[4]:
            await self.delete(first, second)
        return 0
