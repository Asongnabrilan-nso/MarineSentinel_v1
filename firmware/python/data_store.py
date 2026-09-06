# SPDX-FileCopyrightText: Copyright (C) 2026 MarineSentinel Project
# SPDX-License-Identifier: MPL-2.0

from arduino.app_bricks.dbstorage_tsstore import TimeSeriesStore
from arduino.app_utils import Logger

logger = Logger("SensorStore")


class SensorStore:
    """InfluxDB time series storage for MarineSentinel sensor fields."""

    FIELD_TURBIDITY = "turbidity_ntu"
    FIELD_TEMP      = "temperature_c"
    FIELD_ROLL      = "roll_deg"
    FIELD_PITCH     = "pitch_deg"
    FIELD_YAW       = "yaw_deg"

    def __init__(self):
        self._db = TimeSeriesStore()
        self._started = False

    def start(self):
        self._db.start()
        self._started = True
        logger.info("SensorStore connected to InfluxDB")

    def stop(self):
        if self._started:
            self._db.stop()

    def record(self, turbidity_ntu: float, temperature_c: float):
        if not self._started:
            return
        self._db.write_sample(self.FIELD_TURBIDITY, turbidity_ntu)
        self._db.write_sample(self.FIELD_TEMP, temperature_c)

    def record_orientation(self, roll_deg: float, pitch_deg: float, yaw_deg: float):
        if not self._started:
            return
        self._db.write_sample(self.FIELD_ROLL, roll_deg)
        self._db.write_sample(self.FIELD_PITCH, pitch_deg)
        self._db.write_sample(self.FIELD_YAW, yaw_deg)

    def last_turbidity(self):
        return self._db.read_last_sample(self.FIELD_TURBIDITY)

    def last_temperature(self):
        return self._db.read_last_sample(self.FIELD_TEMP)
