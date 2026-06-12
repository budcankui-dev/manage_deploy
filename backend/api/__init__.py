from .nodes import router as nodes_router
from .templates import router as templates_router
from .instances import router as instances_router
from .orders import router as orders_router
from .business_tasks import router as business_tasks_router
from .auth import router as auth_router
from .conversations import router as conversations_router
from .routing import router as routing_router
from .admin import router as admin_router
from .uploads import router as uploads_router
from .baselines import router as baselines_router
from .demo_assets import router as demo_assets_router

__all__ = [
    "nodes_router",
    "templates_router",
    "instances_router",
    "orders_router",
    "business_tasks_router",
    "auth_router",
    "conversations_router",
    "routing_router",
    "admin_router",
    "uploads_router",
    "baselines_router",
    "demo_assets_router",
]
