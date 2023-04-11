from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

import tti_contracts


@dataclass(slots=True)
class DeviceMeta:
    multicast: bool
    updated_at: datetime

    def update_from(self, other: DeviceMeta) -> None:
        if type(self) != type(other):
            raise ValueError(
                f"Can be updated only for other instance of {self.__class__.__name__!r}, not from {type(other)!r}"
            )
        self.multicast = other.multicast
        self.updated_at = other.updated_at

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(multicast={self.multicast!r}, updated_at="{self.updated_at}")'


@dataclass(slots=True)
class DeviceKeys:

    # AppSKey - a session key used by both the Application Server and the end device to encrypt and decrypt the
    #   application data in the data messages for ensuring message confidentiality.
    # AppKey is an AES-128 bit secret key known as the root key. Also known as NwkKey in previous versions of Lora.
    # FNwkSIntKey - a network session key that is used by the end device to calculate the MIC (partially) of all
    #   uplink data messages for ensuring message integrity.
    # SNwkSIntKey - a network session key that is used by the end device to calculate the MIC (partially) of all
    #   uplink data messagse and calculate the MIC of all downlink data messages for ensuring message integrity.
    # NwkSEncKey - a network session key that is used to encrypt and decrypt the payloads with MAC commands of the
    #   uplink and downlink data messages for ensuring message confidentiality

    # app_s_key: bytes | None = field(default=None)
    app_key: bytes | None = field(default=None)
    f_nwk_s_int_key: bytes | None = field(default=None)
    s_nwk_s_int_key: bytes | None = field(default=None)
    nwk_s_enc_key: bytes | None = field(default=None)

    def __eq__(self, other) -> bool:
        if type(self) != type(other):
            return False
        return (
            # self.app_s_key == other.app_s_key and
            self.app_key == other.app_key
            and self.f_nwk_s_int_key == other.f_nwk_s_int_key
            and self.s_nwk_s_int_key == other.s_nwk_s_int_key
            and self.nwk_s_enc_key == other.nwk_s_enc_key
        )

    def update_from(self, other: DeviceKeys) -> None:
        if type(self) != type(other):
            raise ValueError(
                f"Can be updated only for other instance of {self.__class__.__name__!r}, not from {type(other)!r}"
            )
        # self.app_s_key = other.app_s_key
        self.app_key = other.app_key
        self.f_nwk_s_int_key = other.f_nwk_s_int_key
        self.s_nwk_s_int_key = other.s_nwk_s_int_key
        self.nwk_s_enc_key = other.nwk_s_enc_key

    def __repr__(self) -> str:
        nwk_s_enc_key = self.nwk_s_enc_key.hex() if self.nwk_s_enc_key else None
        app_key = self.app_key.hex() if self.app_key else None
        s_nwk_s_int_key = self.s_nwk_s_int_key.hex() if self.s_nwk_s_int_key else None
        f_nwk_s_int_key = self.f_nwk_s_int_key.hex() if self.f_nwk_s_int_key else None
        return (
            f"{self.__class__.__name__}"
            f"(nwk_s_enc_key={nwk_s_enc_key!r}, s_nwk_s_int_key={s_nwk_s_int_key!r}, "
            f"f_nwk_s_int_key={f_nwk_s_int_key!r}, app_key={app_key!r})"
        )


@dataclass(slots=True)
class DeviceIdentifiers:
    device_id: str
    dev_eui: bytes
    app_id: str
    dev_addr: bytes | None = field(default=None)
    join_eui: bytes | None = field(default=None)

    @classmethod
    def from_pb2(cls, pb2_ids: tti_contracts.identifiers_pb2.EndDeviceIdentifiers) -> DeviceIdentifiers:
        return cls(
            device_id=pb2_ids.device_id,
            dev_eui=pb2_ids.dev_eui,
            app_id=pb2_ids.application_ids.application_id,
            dev_addr=pb2_ids.dev_addr if pb2_ids.dev_addr else None,
            join_eui=pb2_ids.join_eui if pb2_ids.join_eui else None,
        )

    def as_pb2(self, crop_addr: bool = True) -> tti_contracts.identifiers_pb2.EndDeviceIdentifiers:
        return tti_contracts.identifiers_pb2.EndDeviceIdentifiers(
            device_id=self.device_id,
            dev_eui=self.dev_eui,
            application_ids=tti_contracts.identifiers_pb2.ApplicationIdentifiers(application_id=self.app_id),
            dev_addr=self.dev_addr if (self.dev_addr and not crop_addr) else None,
            join_eui=self.join_eui if (self.join_eui and not crop_addr) else None,
        )

    def update_from(self, other: DeviceIdentifiers) -> None:
        if type(self) != type(other):
            raise ValueError(
                f"Can be updated only for other instance of {self.__class__.__name__!r}, not from {type(other)!r}"
            )
        self.device_id = other.device_id
        self.dev_eui = other.dev_eui
        self.app_id = other.app_id
        self.dev_addr = other.dev_addr
        self.join_eui = other.join_eui

    def __eq__(self, other) -> bool:
        if type(self) != type(other):
            return False
        return (
            self.device_id == other.device_id
            and self.dev_eui == other.dev_eui
            and self.app_id == other.app_id
            and self.dev_addr == other.dev_addr
            and self.join_eui == other.join_eui
        )

    def __repr__(self) -> str:
        dev_addr = self.dev_addr.hex() if self.dev_addr else None
        join_eui = self.join_eui.hex() if self.join_eui else None
        return (
            f"{self.__class__.__name__}"
            f"(device_id={self.device_id!r}, dev_eui={self.dev_eui.hex()!r}, app_id={self.app_id!r}, "
            f"dev_addr={dev_addr!r}, join_eui={join_eui!r})"
        )

    def clone(self) -> DeviceIdentifiers:
        return replace(self)
