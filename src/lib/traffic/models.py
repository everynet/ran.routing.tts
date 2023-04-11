from __future__ import annotations

from enum import Enum
from typing import Optional

import pylorawan
from pydantic import BaseModel
from ran.routing.core.domains import (
    DownstreamRadio,
    LoRaModulation,
    TransmissionWindow,
    UpstreamRadio,
    UpstreamRejectResultCode,
)


# Uplink models
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class UplinkRadioParams(UpstreamRadio):
    pass


class Uplink(BaseModel):
    correlation_id: str
    used_mic: int
    payload: pylorawan.message.PHYPayload
    radio: UplinkRadioParams

    class Config:
        arbitrary_types_allowed = True

    def make_ack(self, dev_eui: bytes) -> UplinkAck:
        return UplinkAck(correlation_id=self.correlation_id, mic=self.used_mic, dev_eui=dev_eui)

    def make_reject(self, reason: UplinkRejectReason) -> UplinkReject:
        return UplinkReject(correlation_id=self.correlation_id, reason=reason)


class UplinkAck(BaseModel):
    correlation_id: str
    mic: int
    dev_eui: bytes


class UplinkRejectReason(Enum):
    DeviceNotFound = 1
    MicChallengeFail = 2
    InternalError = 3
    NotSupported = 4


class UplinkReject(BaseModel):
    correlation_id: str
    reason: UplinkRejectReason


# Downlink models
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DownlinkRadioParams(DownstreamRadio):
    pass


class DownlinkTiming:
    class TimingBase:
        pass

    class Delay(TimingBase, BaseModel):
        seconds: int

    class GpsTime(TimingBase, BaseModel):
        tmms: int

    class Immediately(TimingBase, BaseModel):
        pass

    @classmethod
    def __instancecheck__(cls, instance):
        return isinstance(instance, cls.TimingBase)


class DownlinkDeviceContext:
    class ContextBase:
        pass

    class Regular(ContextBase, BaseModel):
        dev_eui: bytes
        target_dev_addr: Optional[bytes]

    class Multicast(ContextBase, BaseModel):
        multicast_addr: bytes

    @classmethod
    def __instancecheck__(cls, instance):
        return isinstance(instance, cls.ContextBase)


class Downlink(BaseModel):
    correlation_id: str
    payload: bytes

    radio: DownlinkRadioParams
    timing: DownlinkTiming.TimingBase
    device_ctx: Optional[DownlinkDeviceContext.ContextBase]

    class Config:
        arbitrary_types_allowed = True


class DownlinkResultStatus(Enum):
    OK = 0
    ERROR = 1
    TOO_LATE = 2
    TOO_EARLY = 3


class DownlinkResult(BaseModel):
    correlation_id: str
    status: DownlinkResultStatus


__all__ = (
    # re-exporting
    "DownstreamRadio",
    "TransmissionWindow",
    "UpstreamRadio",
    "UpstreamRejectResultCode",
    "LoRaModulation",
    # Uplink
    "UplinkRadioParams",
    "Uplink",
    "UplinkAck",
    "UplinkRejectReason",
    "UplinkReject",
    # Downlink
    "DownlinkRadioParams",
    "DownlinkTiming",
    "DownlinkDeviceContext",
    "DownlinkResultStatus",
    "DownlinkResult",
)
