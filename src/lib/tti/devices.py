from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Set, Tuple

from structlog import getLogger

from .api import DevId, TTIApi
from .models import DeviceIdentifiers, DeviceKeys, DeviceMeta

logger = getLogger(__name__)


@dataclass(slots=True)
class Device:
    _devices: DeviceList

    ids: DeviceIdentifiers
    keys: DeviceKeys
    meta: DeviceMeta
    dev_addr: bytes | None = field(default=None)

    @property
    def dev_eui(self) -> bytes:
        return self.ids.dev_eui

    def __hash__(self) -> int:
        return hash(self.ids.dev_eui)

    def __eq__(self, other) -> bool:
        if type(self) != type(other):
            return False
        return self.dev_addr == other.dev_addr and self.ids == other.ids and self.keys == other.keys

    def __repr__(self) -> str:
        dev_addr = self.dev_addr.hex() if self.dev_addr else None
        return f"Device(dev_eui={self.dev_eui.hex()!r}, dev_addr={dev_addr!r}, keys={self.keys}, meta={self.meta})"

    async def sync_from_remote(self, update_local_list: bool = True, trigger_update_callback: bool = False):
        remote_device: Device = await self._devices._pull_device_from_remote(self.ids)
        if self.__eq__(remote_device):
            return

        if trigger_update_callback:
            await self._devices.update_hook.on_device_updated(self, remote_device)

        if update_local_list:
            self._devices._update_local_device(remote_device)

        self.dev_addr = remote_device.dev_addr
        self.ids.update_from(remote_device.ids)
        self.keys.update_from(remote_device.keys)
        self.meta.update_from(remote_device.meta)


class BaseUpdateHook(Protocol):
    # Update callbacks, must be redefined in subclasses
    async def on_device_updated(self, old_device: Device, new_device: Device) -> None:
        pass

    async def on_device_add(self, device: Device) -> None:
        pass

    async def on_device_remove(self, device: Device) -> None:
        pass


class _EmptyUpdateHook(BaseUpdateHook):
    async def on_device_updated(self, old_device: Device, new_device: Device) -> None:
        pass

    async def on_device_add(self, device: Device) -> None:
        pass

    async def on_device_remove(self, device: Device) -> None:
        pass


class DeviceList(Protocol):
    @abstractmethod
    def get_device_by_dev_eui(self, dev_eui: bytes) -> Optional[Device]:
        pass

    @abstractmethod
    def get_device_by_dev_addr(self, dev_addr: bytes) -> Optional[Device]:
        pass

    @abstractmethod
    def get_all_devices(self) -> list[Device]:
        pass

    # This method must sync devices with remote
    @abstractmethod
    async def sync_from_remote(self):
        pass

    # Internal methods, required for "Device" interaction
    @abstractmethod
    async def _pull_device_from_remote(self, dev_id: DevId) -> Device:
        pass

    @abstractmethod
    def _update_local_device(self, device: Device):
        pass

    @property
    @abstractmethod
    def update_hook(self) -> BaseUpdateHook:
        pass

    @update_hook.setter
    def update_hook(self, hook) -> None:
        pass


class BaseTTIDeviceList(DeviceList):
    @property
    def update_hook(self) -> BaseUpdateHook:
        return self._update_hook

    @update_hook.setter
    def update_hook(self, hook) -> None:
        logger.debug(f"Update hook set: {hook}")
        self._update_hook = hook

    def __init__(self, tti: TTIApi, update_hook: None | BaseUpdateHook = None) -> None:
        self._api = tti
        self._update_hook = update_hook if update_hook is not None else _EmptyUpdateHook()

    async def _pull_device_from_remote(self, dev_id: "DevId") -> Device:
        ns_data = await self._api.get_device_ns_data(dev_id)
        device_identifiers = DeviceIdentifiers.from_pb2(ns_data.ids)

        # NS can not contain "dev_eui", so, if we already have dev_eui set for device, we just reusing it
        if not device_identifiers.dev_eui and dev_id.dev_eui:  # Both "dev_id" types has "dev_eui" attribute
            logger.warning("NsEndDeviceRegistry missing dev_eui for device, using EndDeviceRegistry dev_eui")
            device_identifiers.dev_eui = dev_id.dev_eui

        def nullify_empty(value: bytes) -> bytes | None:
            if value:
                return value
            else:
                return None

        # TODO: we need better handling of dev_addr changes in TTI handling.
        if ns_data.pending_session.dev_addr:
            ns_keys = ns_data.pending_session.keys
            dev_addr = ns_data.pending_session.dev_addr
        else:
            ns_keys = ns_data.session.keys
            dev_addr = ns_data.session.dev_addr

        root_keys = await self._api.get_js_device_keys(dev_id)
        device_keys = DeviceKeys(
            f_nwk_s_int_key=nullify_empty(ns_keys.f_nwk_s_int_key.key),
            s_nwk_s_int_key=nullify_empty(ns_keys.s_nwk_s_int_key.key),
            nwk_s_enc_key=nullify_empty(ns_keys.nwk_s_enc_key.key),
            app_key=nullify_empty(root_keys.app_key.key) if root_keys else None,
        )

        device_meta = DeviceMeta(
            multicast=ns_data.multicast if ns_data.multicast else False,  # can be just empty str, not strict bool.
            updated_at=ns_data.updated_at.ToDatetime(),
        )

        device = Device(self, dev_addr=dev_addr, ids=device_identifiers, keys=device_keys, meta=device_meta)
        # print(repr(device))
        return device


class ApplicationDeviceList(BaseTTIDeviceList):
    def __init__(
        self,
        tti: TTIApi,
        application_id: str,
        update_hook: None | BaseUpdateHook = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(tti, update_hook)
        self._application_id = application_id
        self._tags = tags if tags is not None else {}
        self._dev_eui_to_device: Dict[bytes, Device] = {}
        self._dev_addr_to_dev_eui: Dict[bytes, bytes] = {}

    def get_all_devices(self) -> list[Device]:
        return list(self._dev_eui_to_device.values())

    def _is_ran_device(self, device) -> bool:
        if len(self._tags) == 0:
            return True
        for tag_name, tag_value in self._tags.items():
            if device.attributes.get(tag_name, None) == tag_value:
                return True
        # logger.debug("Device filtered by attribute", filter=self._tags, dev_eui=device.ids.dev_eui.hex())
        return False

    async def sync_from_remote_legacy(self) -> None:
        dev_eui_to_device: Dict[bytes, Device] = {}
        dev_addr_to_dev_eui: Dict[bytes, bytes] = {}

        async for raw_device in self._api.list_devices(self._application_id):
            if self._is_ran_device(raw_device):
                dev_eui_to_device[raw_device.ids.dev_eui] = await self._pull_device_from_remote(raw_device.ids)

        for dev_eui, device in dev_eui_to_device.items():
            if device.dev_addr:
                dev_addr_to_dev_eui[device.dev_addr] = device.dev_eui

            existed_device = self._dev_eui_to_device.get(dev_eui)
            if not existed_device:
                await self._update_hook.on_device_add(device)
                continue

            if existed_device != device:
                await self._update_hook.on_device_updated(existed_device, device)

        for dev_eui, device in self._dev_eui_to_device.items():
            if dev_eui not in dev_eui_to_device:
                await self._update_hook.on_device_remove(device)

        self._dev_eui_to_device = dev_eui_to_device
        self._dev_addr_to_dev_eui = dev_addr_to_dev_eui

    async def sync_from_remote(self) -> None:
        unchanged_devices: Set[Device] = set()
        new_devices: Set[Device] = set()
        updated_devices: Set[Tuple[Device, Device]] = set()  # Current dev, Updated dev
        removed_devices: Set[Device] = set()

        async for raw_device in self._api.list_devices(self._application_id):
            if not self._is_ran_device(raw_device):
                continue

            current_dev = self._dev_eui_to_device.get(raw_device.ids.dev_eui, None)
            if current_dev is None:
                new_devices.add(await self._pull_device_from_remote(raw_device.ids))
                continue

            updated_dev = await self._pull_device_from_remote(raw_device.ids)
            if current_dev.meta.updated_at < updated_dev.meta.updated_at:
                # If nothing, except "updated_at" is same, just update "updated_at" field, and mark device as unchanged
                if current_dev == updated_dev:
                    current_dev.meta.updated_at = updated_dev.meta.updated_at
                    unchanged_devices.add(current_dev)
                    continue

                updated_devices.add((current_dev, updated_dev))
                continue

            unchanged_devices.add(current_dev)

        synced_devices = unchanged_devices.union(set(u[0] for u in updated_devices))
        existed_devices = set(self._dev_eui_to_device.values())
        removed_devices = existed_devices.difference(synced_devices)

        # print("ACT:", unchanged_devices)
        # print("NEW:", new_devices)
        # print("UPD:", updated_devices)
        # print("REM:", removed_devices)

        for device in removed_devices:
            self._dev_eui_to_device.pop(device.dev_eui)
            if device.dev_addr:
                self._dev_addr_to_dev_eui.pop(device.dev_addr)
            await self._update_hook.on_device_remove(device)

        def set_dev(device):
            self._dev_eui_to_device[device.dev_eui] = device
            if device.dev_addr:
                self._dev_addr_to_dev_eui[device.dev_addr] = device.dev_eui

        for device in new_devices:
            await self._update_hook.on_device_add(device)
            set_dev(device)

        for old_device, new_device in updated_devices:
            await self._update_hook.on_device_updated(old_device, new_device)
            if old_device.dev_addr is not None and new_device.dev_addr != old_device.dev_addr:
                self._dev_addr_to_dev_eui.pop(old_device.dev_addr)
            set_dev(new_device)

        # print("." * 100)
        # print("MAIN:", self._dev_eui_to_device)
        # print("DVADDR:", self._dev_addr_to_dev_eui)
        # print("^" * 100)

    def _update_local_device(self, device: Device) -> None:
        """
        This method adds device changes into local state

        :param device: Updated device
        :type device: Device
        """
        if device.dev_eui not in self._dev_eui_to_device:
            self._dev_eui_to_device[device.dev_eui] = device
            if device.dev_addr:
                self._dev_addr_to_dev_eui[device.dev_addr] = device.dev_eui
            return

        dev_addr = self._dev_eui_to_device.get(device.dev_eui).dev_addr  # type: ignore # it will already exist in dict
        if dev_addr != device.dev_addr:
            self._dev_addr_to_dev_eui.pop(dev_addr, None)  # type: ignore
            if device.dev_addr:
                self._dev_addr_to_dev_eui[device.dev_addr] = device.dev_eui

    def get_device_by_dev_eui(self, dev_eui: bytes) -> Optional[Device]:
        return self._dev_eui_to_device.get(dev_eui, None)

    def get_device_by_dev_addr(self, dev_addr: bytes) -> Optional[Device]:
        return self._dev_eui_to_device.get(self._dev_addr_to_dev_eui.get(dev_addr, None), None)  # type: ignore


class MultiApplicationDeviceList(BaseTTIDeviceList):
    def __init__(
        self,
        tti: TTIApi,
        update_hook: None | BaseUpdateHook = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(tti, update_hook)
        self._applications: Dict[int, ApplicationDeviceList] = {}
        self._tags = tags if tags is not None else {}

    async def sync_from_remote(self) -> None:
        application_ids = set()

        async for application in self._api.list_applications():
            app_id = application.ids.application_id

            if app_id not in self._applications:
                app_dev_list = ApplicationDeviceList(
                    tti=self._api,
                    update_hook=self._update_hook,
                    application_id=app_id,
                    tags=self._tags,
                )
                self._applications[app_id] = app_dev_list

            application_ids.add(app_id)
            await self._applications[app_id].sync_from_remote()

        # Removing applications lists, which was deleted
        for application_id in list(self._applications.keys()):
            if application_id not in application_ids:
                del self._applications[application_id]

    def get_device_by_dev_eui(self, dev_eui: bytes) -> Optional[Device]:
        for app_list in self._applications.values():
            device = app_list.get_device_by_dev_eui(dev_eui)
            if device:
                return device
        return None

    def get_device_by_dev_addr(self, dev_addr: bytes) -> Optional[Device]:
        for app_list in self._applications.values():
            device = app_list.get_device_by_dev_addr(dev_addr)
            if device:
                return device
        return None

    def _update_local_device(self, device) -> None:
        for app_list in self._applications.values():
            app_device = app_list.get_device_by_dev_eui(device.dev_eui)
            if app_device:
                app_list._update_local_device(device)
                break
        return None

    def get_all_devices(self):
        all_devices = []
        for app_list in self._applications.values():
            all_devices.extend(app_list.get_all_devices())
        return all_devices
