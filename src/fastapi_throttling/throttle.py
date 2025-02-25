from redis import Redis
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ThrottlingResponse(JSONResponse):
    def __init__(self):
        content = {"detail": "Too Many Requests"}
        status_code = 429
        super().__init__(status_code=status_code, content=content)


class ThrottlingMiddleware:
    """
    Middleware for throttling requests based on IP address and access token.

    The middleware uses a Redis server to keep track of the request counts.
    If a limit is reached within a specified time window, further requests
    are blocked until the window is expired.

    Attributes:
        app: The FastAPI application to apply the middleware to.
        limit: The maximum number of requests allowed within the time window.
        window: The time window in seconds.
        redis: The Redis client instance.

    Methods:
        __call__: Intercept incoming requests and apply the rate limiting.
        has_exceeded_rate_limit: Check if the number of requests has exceeded the limit
            for a given identifier.
    """

    def __init__(
        self,
        app: ASGIApp,
        limit: int = 100,
        window: int = 60,
        token_header: str = "Authorization",
        redis: Redis | None = None,
    ) -> None:
        self.app = app
        self.token_header = token_header
        self.limit = limit
        self.window = window
        self.redis = redis
        if not self.redis:
            self.redis = Redis()

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        client_ip = headers.get(
            "x-forwarded-for", next(iter(scope["client"][0]), None)
        )
        # Throttle by IP
        if client_ip and await self.has_exceeded_rate_limit(client_ip):
            response = ThrottlingResponse()
            await response(scope, receive, send)
            return

        token = headers.get(self.token_header)
        # Throttle by Token
        if token and await self.has_exceeded_rate_limit(token):
            response = ThrottlingResponse()
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
        return

    async def has_exceeded_rate_limit(self, identifier: str) -> bool:
        current_count = self.redis.get(identifier)

        if current_count is None:
            # This is the first request with this identifier within the window
            self.redis.set(identifier, 1, ex=self.window)  # Start a new window
            return False

        if int(current_count) < self.limit:
            # Increase the request count
            self.redis.incr(identifier)
            return False

        return True
