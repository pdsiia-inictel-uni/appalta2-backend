from fastapi import FastAPI
from app.routes.user import router as user_router
from app.routes.measurements import router as measurements_router
from app.routes.stations import router as stations_router
import logging
#from . import routes
#from . import models, database, routes

#models.Base.metadata.create_all(bind=database.engine)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


app = FastAPI(title="Backend Appalta2")

app.include_router(
    user_router,
    prefix="/api/v1",
    tags=["Users"],
)

app.include_router(
    measurements_router,
    prefix="/api/v1",
    tags=["Measurements"],
)

app.include_router(
    stations_router,
    prefix="/api/v1",
    tags=["Stations"],
)

#app.include_router(routes.router, prefix="/api", tags=["auth"])