from pydantic import BaseModel


class SetTruckRequest(BaseModel):
    truck_id: str


class SetTruckResponse(BaseModel):
    message: str
    truck_id: str

