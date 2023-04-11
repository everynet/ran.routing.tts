import structlog
from ran.routing.core import Core as RANCore
from ran.routing.core.multicast_groups.exceptions import ApiMulticastGroupAlreadyExistsError
from ran.routing.core.routing_table.exceptions import ApiDeviceAlreadyExistsError

from lib.tti.devices import BaseUpdateHook, Device

logger = structlog.getLogger(__name__)


class RanSyncHook(BaseUpdateHook):
    def __init__(self, ran_core: RANCore) -> None:
        self.ran_core = ran_core

        self._devices = _RanSyncDevices(self.ran_core)
        self._multicast = _RanSyncMulticast(self.ran_core)

    async def on_device_add(self, device: Device) -> None:
        if device.meta.multicast:
            logger.warning("Multicast devices are not supported", hook="on_device_add")
        else:
            return await self._devices.on_device_add(device)

    async def on_device_remove(self, device: Device) -> None:
        if device.meta.multicast:
            logger.warning("Multicast devices are not supported", hook="on_device_remove")
        else:
            return await self._devices.on_device_remove(device)

    async def on_device_updated(self, old_device: Device, new_device: Device) -> None:
        if old_device.meta.multicast or new_device.meta.multicast:
            logger.warning("Multicast devices are not supported", hook="on_device_updated")
        else:
            return await self._devices.on_device_updated(old_device, new_device)


class _RanSyncDevices(BaseUpdateHook):
    def __init__(self, ran_core: RANCore) -> None:
        self.ran_core = ran_core

    async def on_device_add(self, device: Device) -> None:
        try:
            dev_eui = int.from_bytes(device.dev_eui, "big")
            dev_addr = None
            if device.dev_addr:
                dev_addr = int.from_bytes(device.dev_addr, "big")
            logger.info(
                "Adding device",
                dev_eui=device.dev_eui.hex(),
                dev_addr=format(dev_addr, "08x") if dev_addr else "<not-provided>",
            )
            await self.ran_core.routing_table.insert(dev_eui=dev_eui, join_eui=dev_eui, dev_addr=dev_addr)

        except ApiDeviceAlreadyExistsError:
            # logger.warning("Device already exists. Update skipped.", dev_eui=device.dev_eui.hex())
            logger.warning("Device already exists. Attempting to update device in RAN", dev_eui=device.dev_eui.hex())
            # Resync device. Fetch data from remote and use it as old device in sync.
            ran_device = (await self.ran_core.routing_table.select([dev_eui]))[0]
            device_ids = device.ids.clone()
            if ran_device.active_dev_addr:
                device_ids.dev_addr = ran_device.active_dev_addr.to_bytes(4, "big")
            old_device = Device(_devices=device._devices, ids=device_ids, keys=device.keys, meta=device.meta)
            await self.on_device_updated(old_device, device)

    async def on_device_remove(self, device: Device) -> None:
        logger.info("Removing device", dev_eui=device.dev_eui.hex())
        dev_eui = int.from_bytes(device.dev_eui, "big")
        await self.ran_core.routing_table.delete([dev_eui])

    async def on_device_updated(self, old_device: Device, new_device: Device) -> None:
        if old_device == new_device:
            logger.info("Device already synced", dev_eui=new_device.dev_eui.hex())

        if old_device.dev_addr != new_device.dev_addr:
            dev_eui = int.from_bytes(new_device.dev_eui, "big")
            new_dev_addr, old_dev_addr = None, None
            if new_device.dev_addr:
                new_dev_addr = int.from_bytes(new_device.dev_addr, "big")
            if old_device.dev_addr:
                old_dev_addr = int.from_bytes(old_device.dev_addr, "big")

            if new_dev_addr is None:
                logger.info("No new dev_addr specified for device", dev_eui=new_device.dev_eui.hex())
                return

            logger.info(
                "Updating device's dev_addr in RAN",
                dev_eui=new_device.dev_eui.hex(),
                old_dev_addr=format(old_dev_addr, "08x") if old_device.dev_addr else "<not-provided>",
                new_dev_addr=format(new_dev_addr, "08x") if new_device.dev_addr else "<not-provided>",
            )
            # TODO: better update sequence
            await self.ran_core.routing_table.update(dev_eui=dev_eui, join_eui=dev_eui, active_dev_addr=new_dev_addr)
            # await self.ran_core.routing_table.delete([dev_eui])
            # await self.ran_core.routing_table.insert(dev_eui=dev_eui, join_eui=dev_eui, dev_addr=dev_addr)
            logger.info("Device's dev_addr synced with RAN", dev_eui=new_device.dev_eui.hex())


# TODO: multicast


class _RanSyncMulticast:
    def __init__(self, ran_core: RANCore) -> None:
        self.ran_core = ran_core

    # async def on_group_add(self, device: Device) -> None:
    #     if not device.dev_addr:
    #         logger.warning(
    #             "Multicast group not synced with ran, because it has no assigned 'Addr'",
    #             group_id=device.ids.device_id,
    #         )
    #         return

    #     group_addr = int(device.dev_addr, 16)
    #     try:
    #         await self.ran_core.multicast_groups.create_multicast_group(name=group.name, addr=group_addr)
    #         logger.info("Multicast group added", addr=group.addr, name=group.name)
    #     except ApiMulticastGroupAlreadyExistsError:
    #         logger.warning("Multicast group already exists. Attempting to sync multicast group.", addr=group.addr)
    #         # If group already exists, fetch data from remote and perform update, assuming something was changed
    #         ran_group = (await self.ran_core.multicast_groups.get_multicast_groups(int(group.addr, 16)))[0]
    #         old_group = chirpstack.MulticastGroup(
    #             _groups=self,
    #             id=group.id,
    #             addr=group.addr,
    #             name=ran_group.name,
    #             devices=set(f"{d:016x}" for d in ran_group.devices),
    #         )
    #         return await self.on_group_updated(old_group=old_group, new_group=group)

    #     existed_devices = await self.ran_core.routing_table.select(
    #         dev_euis=list(int(dev_eui, 16) for dev_eui in group.devices)
    #     )
    #     existed_dev_euis = set(f"{device.dev_eui:016x}" for device in existed_devices)
    #     for device_eui in group.devices:
    #         if device_eui not in existed_dev_euis:
    #             logger.warning(
    #                 "Device was not added to multicast group, because it not present in routing table",
    #                 addr=group.addr,
    #                 dev_eui=device_eui,
    #             )
    #             continue
    #         await self.ran_core.multicast_groups.add_device_to_multicast_group(
    #             addr=group_addr, dev_eui=int(device_eui, 16)
    #         )
    #         logger.info("Device added to multicast group", addr=group.addr, dev_eui=device_eui)

    #     logger.info("Multicast group synced", addr=group.addr)

    # async def on_group_remove(self, group: chirpstack.MulticastGroup) -> None:
    #     if not group.addr:
    #         logger.warning(
    #             f"Multicast group with id {group.id!r} not synced with ran, because no dev_addr assigned to it"
    #         )
    #         return

    #     group_addr = int(group.addr, 16)
    #     await self.ran_core.multicast_groups.delete_multicast_groups([group_addr])
    #     logger.info("Multicast group removed", addr=group.addr, name=group.name)

    # async def on_group_updated(
    #     self, old_group: chirpstack.MulticastGroup, new_group: chirpstack.MulticastGroup
    # ) -> None:
    #     if old_group == new_group:
    #         logger.info("Multicast group already in sync", addr=new_group.addr)
    #         return

    #     if old_group.addr != new_group.addr or old_group.name != new_group.name:
    #         if old_group.addr != new_group.addr:
    #             logger.info(
    #                 f"Updating multicast group addr: {old_group.addr!r} -> {new_group.addr!r}",
    #                 old_addr=old_group.addr,
    #                 new_addr=new_group.addr,
    #             )
    #         if old_group.name != new_group.name:
    #             logger.info(
    #                 f"Updating multicast group name: {old_group.name!r} -> {new_group.name!r}",
    #                 addr=new_group.addr,
    #                 old_name=old_group.name,
    #                 new_name=new_group.name,
    #             )

    #         old_group_addr = int(old_group.addr, 16)  # type: ignore
    #         new_group_addr = int(new_group.addr, 16)  # type: ignore
    #         new_name = new_group.name
    #         await self.ran_core.multicast_groups.update_multicast_group(
    #             addr=old_group_addr, new_addr=new_group_addr, new_name=new_name
    #         )
    #         logger.info("Multicast group updated", addr=new_group.addr)

    #     if old_group.devices != new_group.devices:
    #         for dev_to_remove in old_group.devices - new_group.devices:
    #             device_removed = await self.ran_core.multicast_groups.remove_device_from_multicast_group(
    #                 addr=int(new_group.addr, 16), dev_eui=int(dev_to_remove, 16)  # type: ignore
    #             )
    #             if device_removed:
    #                 logger.info("Device removed from multicast group", addr=new_group.addr, dev_eui=dev_to_remove)

    #         devices_to_add = new_group.devices - old_group.devices
    #         if len(devices_to_add) > 0:
    #             existed_devices = await self.ran_core.routing_table.select(
    #                 dev_euis=list(int(dev_eui, 16) for dev_eui in devices_to_add)
    #             )
    #             existed_dev_euis = set(f"{device.dev_eui:016x}" for device in existed_devices)
    #             for dev_eui_to_add in devices_to_add:
    #                 if dev_eui_to_add not in existed_dev_euis:
    #                     logger.warning(
    #                         "Device was not added to multicast group, because it not present in routing table",
    #                         addr=new_group.addr,
    #                         dev_eui=dev_eui_to_add,
    #                     )
    #                     continue
    #                 await self.ran_core.multicast_groups.add_device_to_multicast_group(
    #                     addr=int(new_group.addr, 16), dev_eui=int(dev_eui_to_add, 16)  # type: ignore
    #                 )
    #                 logger.info("Device added to multicast group", addr=new_group.addr, dev_eui=dev_eui_to_add)
    #         logger.info("Multicast group devices synced", addr=new_group.addr)
