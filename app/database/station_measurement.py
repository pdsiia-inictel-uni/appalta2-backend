def create_measurement(
    db,
    measurement
):

    db.add(measurement)

    db.commit()

    db.refresh(measurement)

    return measurement