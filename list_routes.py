from app.main import app

for route in app.routes:
    # Si tiene sub-rutas (APIRouter)
    if hasattr(route, "routes"):
        for sub_route in route.routes:
            print(f"Sub-Route: {sub_route.path} [{','.join(sub_route.methods)}]")
    else:
        print(f"Route: {route.path} [{','.join(route.methods or [])}]")
