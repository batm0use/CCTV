from web.routers.api import router as api_router
from web.routers.auth import router as auth_router
from web.routers.footage import router as footage_router
from web.routers.live import router as live_router

all_routers = [auth_router, live_router, footage_router, api_router]
