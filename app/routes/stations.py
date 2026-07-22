from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database import station as station_db
from app.schemas.station import StationResponse

router = APIRouter()

@router.get(
        "/stations",
        response_model = list[StationResponse])
async def get_all_stations(
    db: Session = Depends(get_db)
):
    return station_db.get_all_stations(db)
