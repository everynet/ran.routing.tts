import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Optional

import pylorawan
import structlog
import tti_contracts
from google.protobuf.timestamp_pb2 import Timestamp

from lib.gps_time import utc_to_gps
from lib.tti.devices import Device

from .. import cache, mqtt, tti
from ..logging_conf import lazy_protobuf_fmt
from .models import (
    Downlink,
    DownlinkDeviceContext,
    DownlinkRadioParams,
    DownlinkResult,
    DownlinkResultStatus,
    DownlinkTiming,
    LoRaModulation,
    Uplink,
    UplinkAck,
    UplinkReject,
    UplinkRejectReason,
)

logger = structlog.getLogger(__name__)


def proto_timestamp_is_empty(ts: Timestamp) -> bool:
    return not (bool(ts.seconds) or bool(ts.nanos))


class TTIStatusUpdater:
    def __init__(self, mqtt: mqtt.MQTTClient) -> None:
        self.mqtt = mqtt

    async def submit_status(self):
        stats = tti_contracts.gateway_pb2.GatewayStatus()
        stats.time.FromDatetime(datetime.utcnow())
        await self.mqtt.publish("status", stats.SerializeToString())
        logger.debug("Gateway status sent", stats=lazy_protobuf_fmt(stats))

    async def submit_initial_status(self):
        stats = tti_contracts.gateway_pb2.GatewayStatus()
        stats.boot_time.FromDatetime(datetime.utcnow())
        await self.mqtt.publish("status", stats.SerializeToString())
        logger.debug("Gateway initial status sent", stats=lazy_protobuf_fmt(stats))


class GatewayClockScheduler:
    TIMER_SIZE = 2**32
    TIME_UNIT = int(1e6)

    def __init__(self, interval_sec: int = 15) -> None:
        self._interval_ms = interval_sec * self.TIME_UNIT
        self._clock = 0  # Grows in "_interval_ms" with each tmst, with overflow on "TIMER_SIZE"
        self._scheduled: cache.Cache[str, int] = cache.Cache(ttl=interval_sec * 2)

    @property
    def min_interval_ms(self):
        return self._interval_ms

    @property
    def rps(self) -> float:
        return self.TIMER_SIZE / self._interval_ms

    def _next_tmst(self) -> int:
        current_tmst = self._clock
        self._clock = (current_tmst + self._interval_ms) % self.TIMER_SIZE
        return current_tmst

    def schedule_uplink_tmst(self, corr_id: str) -> int:
        tmst = self._next_tmst()
        self._scheduled.set(corr_id, tmst)
        return tmst

    def calculate_downlink_tmst(self, corr_id: str, downlink_tmst: int) -> int | None:
        uplink_tmst = self._scheduled.pop(corr_id, None)
        if uplink_tmst is None:
            logger.debug("Can't calculate downlink tmst - uplink tmst not tracked")
            return None

        real_tmst = downlink_tmst - uplink_tmst
        if real_tmst <= 0:
            # Means, downlink tmst set after clock overflow, so we need sum ms before and after overflow.
            before_overflow = self.TIMER_SIZE - uplink_tmst
            after_overflow = downlink_tmst
            real_tmst = before_overflow + after_overflow

        logger.debug(
            "Real tmst evaluated for downlink",
            uplink_tmst=uplink_tmst,
            downlink_tmst=downlink_tmst,
            real_tmst=real_tmst,
        )
        return real_tmst


class TTITrafficRouter:
    CORRELATION_ID_PREFIX = "ran:uplink:"
    TTI_DOWNLINK_CORR_ID_PREFIX = "ns:downlink:"
    TTI_UPLINK_CORR_ID = "uplink:"

    def __init__(
        self,
        gateway_id: str,
        mqtt_client: mqtt.MQTTClient,
        devices: tti.DeviceList,
        # multicast_groups: chirpstack.MulticastGroupList,
    ):
        self.gateway_id = gateway_id
        self.devices = devices
        self.mqtt_client = mqtt_client
        # self.multicast_groups = multicast_groups

        # Track devices, who send uplinks
        self._correlation_id_to_device: cache.Cache[str, Device] = cache.Cache(ttl=100)
        # Communication
        self._downlinks_queue: asyncio.Queue[Downlink] = asyncio.Queue()

        # Storing amount of not-processed ack's per downlink_id
        self._ignored_downlinks_count: cache.Cache[int, int] = cache.Cache(ttl=100)

        # Virtual gateway clock emulator, used to track tmst for uplinks/downlinks
        self._tmst_scheduler = GatewayClockScheduler()

        self._tti_extra_corr_ids: cache.Cache[str, list[str]] = cache.Cache()

    @property
    def downstream_rx(self):
        return self._downlinks_queue

    def _create_tti_uplink(self, uplink: Uplink) -> tti_contracts.messages_pb2.UplinkMessage:
        radio_params = uplink.radio
        time_now = datetime.utcnow()

        lora_dr = tti_contracts.lorawan_pb2.LoRaDataRate()
        lora_dr.spreading_factor = uplink.radio.lora.spreading
        lora_dr.bandwidth = uplink.radio.lora.bandwidth
        lora_dr.coding_rate = "4/5"
        tx_settings = tti_contracts.lorawan_pb2.TxSettings()
        tx_settings.frequency = radio_params.frequency
        tx_settings.enable_crc = False
        tx_settings.time.FromDatetime(time_now)
        tx_settings.data_rate.MergeFrom(tti_contracts.lorawan_pb2.DataRate(lora=lora_dr))

        gw_id = tti_contracts.identifiers_pb2.GatewayIdentifiers(gateway_id=self.gateway_id)
        rx_metadata = tti_contracts.metadata_pb2.RxMetadata()
        rx_metadata.rssi = radio_params.rssi
        rx_metadata.snr = radio_params.snr
        rx_metadata.gateway_ids.MergeFrom(gw_id)
        rx_metadata.time.FromDatetime(time_now)
        rx_metadata.received_at.FromDatetime(time_now)
        rx_metadata.timestamp = self._tmst_scheduler.schedule_uplink_tmst(uplink.correlation_id)
        # TODO: Ensure correct GPS time for uplink
        rx_metadata.gps_time.FromDatetime(utc_to_gps(time_now))

        tti_uplink = tti_contracts.messages_pb2.UplinkMessage()
        tti_uplink.raw_payload = uplink.payload.generate()
        tti_uplink.correlation_ids.append(f"{self.CORRELATION_ID_PREFIX}{uplink.correlation_id}")
        tti_uplink.settings.MergeFrom(tx_settings)
        tti_uplink.rx_metadata.append(rx_metadata)

        return tti_uplink

    def _extract_correlation_id(self, downlink: tti_contracts.messages_pb2.DownlinkMessage) -> str | None:
        # TODO: Better correlation_id extraction
        correlation_id = None
        for corr_id in downlink.correlation_ids:
            if corr_id.startswith(self.CORRELATION_ID_PREFIX):
                correlation_id = corr_id[len(self.CORRELATION_ID_PREFIX) :]
                break

        if correlation_id is None:
            for corr_id in downlink.correlation_ids:
                if corr_id.startswith(self.TTI_DOWNLINK_CORR_ID_PREFIX):
                    correlation_id = corr_id[len(self.TTI_DOWNLINK_CORR_ID_PREFIX) :]
                    break

        return correlation_id

    def _create_ran_downlink(self, tti_gw_downlink: tti_contracts.gatewayserver_pb2.GatewayDown) -> Downlink:
        downlink = tti_gw_downlink.downlink_message
        correlation_id = self._extract_correlation_id(downlink)

        if correlation_id is None:
            raise ValueError("No correlation_id extracted from downlink!")

        tx_info_type = downlink.WhichOneof("settings")
        if tx_info_type != "scheduled":
            raise ValueError(f"Unknown downlink type: {tx_info_type!r}")

        if not downlink.scheduled.data_rate.lora:
            raise ValueError("LoRa modulation not provided, other modulations are not supported")

        lora_modulation = LoRaModulation(
            bandwidth=downlink.scheduled.data_rate.lora.bandwidth,
            spreading=downlink.scheduled.data_rate.lora.spreading_factor,
        )
        downlink_radio_params = DownlinkRadioParams(frequency=downlink.scheduled.frequency, lora=lora_modulation)

        # Testing, is this downlink is answer to uplink?
        for corr_id in downlink.correlation_ids:
            if self.TTI_UPLINK_CORR_ID in corr_id:
                class_b_c = False
                break
        else:
            class_b_c = True

        timing: DownlinkTiming.TimingBase
        if not class_b_c:
            # Class A
            downlink_tmst = downlink.scheduled.timestamp
            if downlink_tmst is None:
                raise ValueError("No timestamp provided for class A downlink")
            real_tmst = self._tmst_scheduler.calculate_downlink_tmst(correlation_id, downlink_tmst)
            if real_tmst is None:
                raise ValueError("Error calculating real tmst for downlink")

            timing = DownlinkTiming.Delay(seconds=int(real_tmst / 1e6))

            # If scheduled timing is greater, then max rx2 (supported by ran), we can't send it to ran-routing
            if not (0 < timing.seconds < 16):
                raise ValueError(f"Delay out of bounds: '0 < delay < 16', delay={timing.seconds}")
            logger.debug("Downlink class A prepared", timing=repr(timing))

        else:
            if not proto_timestamp_is_empty(downlink.scheduled.time):
                # Class B
                # TODO: ensure we are not need extra data translations for gps time
                seconds = downlink.scheduled.time.seconds
                nanos = downlink.scheduled.time.nanos
                # tmms measured in milliseconds
                timing = DownlinkTiming.GpsTime(tmms=seconds * 10**3 + nanos // 10**6)
                logger.debug("Downlink class B prepared", timing=repr(timing))
            else:
                # Class C
                timing = DownlinkTiming.Immediately()
                logger.debug("Downlink class C prepared", timing=repr(timing))

        ran_downlink = Downlink(
            correlation_id=correlation_id,
            payload=downlink.raw_payload,
            radio=downlink_radio_params,
            timing=timing,
            device_ctx=None,
        )
        # print(repr(ran_downlink))
        return ran_downlink

    def _check_mic(self, phy_payload: pylorawan.message.PHYPayload, nwk_key: bytes) -> bool:
        return pylorawan.common.verify_mic_phy_payload(phy_payload, nwk_key)

    async def _send_uplink(self, uplink: Uplink):
        tti_uplink = self._create_tti_uplink(uplink)
        await self.mqtt_client.publish("up", tti_uplink.SerializeToString())
        logger.debug("Uplink message forwarded to TTI", tti_uplink=lazy_protobuf_fmt(tti_uplink))

    async def handle_upstream(self, uplink: Uplink) -> UplinkReject | UplinkAck:
        phy_payload = uplink.payload
        if phy_payload.mhdr.mtype == pylorawan.message.MType.JoinRequest:
            return await self._handle_join_request(uplink)
        elif phy_payload.mhdr.mtype in (
            pylorawan.message.MType.ConfirmedDataUp,
            pylorawan.message.MType.UnconfirmedDataUp,
        ):
            return await self._handle_uplink(uplink)
        else:
            logger.error(f"Unknown message type: {phy_payload.mhdr.mtype!r}")
            return uplink.make_reject(reason=UplinkRejectReason.NotSupported)

    async def _handle_uplink(self, uplink: Uplink) -> UplinkReject | UplinkAck:
        dev_addr = uplink.payload.payload.fhdr.dev_addr.to_bytes(4, "big")

        device = self.devices.get_device_by_dev_addr(dev_addr)
        if not device:
            logger.warning("handle_uplink: device not found", dev_addr=dev_addr.hex())
            return uplink.make_reject(reason=UplinkRejectReason.DeviceNotFound)

        if not self._check_mic(uplink.payload, device.keys.nwk_s_enc_key):  # type: ignore
            return uplink.make_reject(reason=UplinkRejectReason.MicChallengeFail)

        logger.debug(f"Mic challenge successful, handling {uplink.payload.mhdr.mtype!r} message.", uplink=repr(uplink))
        self._correlation_id_to_device.set(uplink.correlation_id, device)
        await self._send_uplink(uplink)
        uplink_ack = uplink.make_ack(dev_eui=device.dev_eui)
        logger.debug("UplinkAck message created", uplink_ack=repr(uplink_ack), correlation_id=uplink.correlation_id)
        return uplink_ack

    async def _handle_join_request(self, uplink: Uplink) -> UplinkReject | UplinkAck:
        dev_eui = uplink.payload.payload.dev_eui.to_bytes(8, "big")

        device = self.devices.get_device_by_dev_eui(dev_eui)
        if not device:
            logger.warning("handle_join_request: device not found", dev_eui=dev_eui.hex())
            return uplink.make_reject(reason=UplinkRejectReason.DeviceNotFound)

        if device.keys.app_key is None:
            logger.warning("Join cannot be processed, nwk_key/app_key not set!", dev_eui=dev_eui.hex())
            return uplink.make_reject(reason=UplinkRejectReason.InternalError)

        if not self._check_mic(uplink.payload, device.keys.app_key):  # type: ignore
            return uplink.make_reject(reason=UplinkRejectReason.MicChallengeFail)

        logger.debug(f"Mic challenge successful, handling {uplink.payload.mhdr.mtype!r} message.", uplink=repr(uplink))
        self._correlation_id_to_device.set(uplink.correlation_id, device)
        await self._send_uplink(uplink)
        uplink_ack = uplink.make_ack(dev_eui=device.dev_eui)
        logger.debug("UplinkAck message created", uplink_ack=repr(uplink_ack))
        return uplink_ack

    async def _send_tx_ack(self, correlation_id: str, ack_status: tti_contracts.messages_pb2.TxAcknowledgment.Result):
        downlink_tx_ack = tti_contracts.messages_pb2.TxAcknowledgment(result=ack_status)

        # TODO: is it necessary?
        for corr_id in self._tti_extra_corr_ids.pop(correlation_id, []):  # type: ignore
            downlink_tx_ack.correlation_ids.append(corr_id)

        downlink_tx_ack.correlation_ids.append(f"{self.CORRELATION_ID_PREFIX}{correlation_id}")

        await self.mqtt_client.publish("down/ack", downlink_tx_ack.SerializeToString())
        logger.debug("DownlinkTXAck forwarded to TTI", tx_ack=lazy_protobuf_fmt(downlink_tx_ack))

    async def handle_downstream_result(self, downlink_result: DownlinkResult) -> None:
        logger.debug("Handling downstream result", downlink_result=repr(downlink_result))
        if downlink_result.status == DownlinkResultStatus.OK:
            ack_status = tti_contracts.messages_pb2.TxAcknowledgment.Result.SUCCESS
        elif downlink_result.status == DownlinkResultStatus.TOO_LATE:
            ack_status = tti_contracts.messages_pb2.TxAcknowledgment.Result.TOO_LATE
        elif downlink_result.status == DownlinkResultStatus.TOO_EARLY:
            ack_status = tti_contracts.messages_pb2.TxAcknowledgment.Result.TOO_EARLY
        elif downlink_result.status == DownlinkResultStatus.ERROR:
            ack_status = tti_contracts.messages_pb2.TxAcknowledgment.Result.UNKNOWN_ERROR
        else:
            logger.error(
                f"Unknown downlink result status: {downlink_result.status}",
                correlation_id=downlink_result.correlation_id,
            )
            return
        await self._send_tx_ack(downlink_result.correlation_id, ack_status)

    async def _fetch_downlink_device_context(self, downlink: Downlink) -> Optional[DownlinkDeviceContext.ContextBase]:
        device: Device | None = self._correlation_id_to_device.get(downlink.correlation_id, None)
        mhdr = pylorawan.message.MHDR.parse(downlink.payload[:1])

        # First branch - JoinAccept. It will use device data, stored in cache after handling uplink.
        if mhdr.mtype == pylorawan.message.MType.JoinAccept:
            if not device:
                # This branch is unreachable in normal conditions, because JoinAccept is answer to uplink, so we
                # will have this device in cache already.
                logger.warning("Missing device context for JoinAccept message")
                return None

            # If this is join - we need to force update device's new addr in local storage
            await device.sync_from_remote(trigger_update_callback=True, update_local_list=True)
            logger.debug(
                "Device list synced for newly joined device",
                dev_eui=device.dev_eui.hex(),
                new_addr=device.dev_addr.hex() if device.dev_addr else "<not-provided>",
            )
            logger.debug(
                "Device context obtained from cache (JoinAccept)",
                correlation_id=downlink.correlation_id,
                dev_eui=device.dev_eui.hex(),
                dev_addr=device.dev_addr.hex() if device.dev_addr else None,
            )
            return DownlinkDeviceContext.Regular(dev_eui=device.dev_eui, target_dev_addr=device.dev_addr)

        # If this is not JoinAccept - it can be class A downlink, so we use device from cache.
        if device is not None:
            self._correlation_id_to_device.pop(downlink.correlation_id)
            logger.debug(
                "Device context obtained from cache (answering to uplink)",
                correlation_id=downlink.correlation_id,
                dev_eui=device.dev_eui.hex(),
                dev_addr=device.dev_addr.hex() if device.dev_addr else None,
            )
            return DownlinkDeviceContext.Regular(dev_eui=device.dev_eui)

        # We can handle only ConfirmedDataDown/UnconfirmedDataDown downlinks
        if mhdr.mtype not in (
            pylorawan.message.MType.ConfirmedDataDown,
            pylorawan.message.MType.UnconfirmedDataDown,
        ):
            logger.warning("Downlink has unknown type", downlink_type=repr(mhdr.mtype))
            return None

        # If this downlink is not JoinAccept or class A downlink, we are trying to obtain device by it's DevAddr.
        # Here we parsing lora message, to extract target device's DevAddr
        parsed_downlink = pylorawan.message.PHYPayload.parse(downlink.payload)
        dev_addr = parsed_downlink.payload.fhdr.dev_addr.to_bytes(4, "big")
        device = self.devices.get_device_by_dev_addr(dev_addr)

        # If device found in devices list, we are currently processing B/C downlink. Device's DevEui found.
        if device is not None:
            logger.debug(
                "Device context obtained (class B/C downlink)",
                dev_addr=dev_addr.hex(),
                dev_eui=device.dev_eui.hex(),
            )
            return DownlinkDeviceContext.Regular(dev_eui=device.dev_eui)
        logger.debug("Could not obtain device context for device, looking in multicast groups", dev_addr=dev_addr.hex())

        # If no device with provided DevAddr found, trying to obtain multicast group with this addr.
        # It means, we are processing mulitcast downlink for class B/C now.
        # TODO: multicast
        # multicast_group = self.multicast_groups.get_group_by_addr(str_dev_addr)
        # if multicast_group is not None:
        #     logger.debug("Device context obtained (multicast group)", multicast_addr=str_dev_addr)
        #     return DownlinkDeviceContext.Multicast(multicast_addr=multicast_group.addr)
        # logger.debug("No multicast group context found", multicast_addr=str_dev_addr)

        # If nothing is found after all steps - we have no devices or multicast groups with this DevAddr stored.
        return None

    async def _process_downlink(self, tti_gw_downlink: tti_contracts.gatewayserver_pb2.GatewayDown):
        try:
            ran_downlink = self._create_ran_downlink(tti_gw_downlink)
        except Exception:
            logger.exception("Error translating TTI downlink to internal format")
            return

        # TODO: is it necessary?
        extra_corr_id = []
        for corr_id in tti_gw_downlink.downlink_message.correlation_ids:
            if not corr_id.startswith(self.CORRELATION_ID_PREFIX):
                extra_corr_id.append(corr_id)

        self._tti_extra_corr_ids.set(ran_downlink.correlation_id, extra_corr_id)

        device_ctx = await self._fetch_downlink_device_context(ran_downlink)
        if device_ctx is not None:
            # Setting device context, required for ran router
            ran_downlink.device_ctx = device_ctx
            logger.debug("Downlink message assembled", downlink=repr(ran_downlink))
            await self._downlinks_queue.put(ran_downlink)
        else:
            logger.warning(
                "Missed device context for downlink, skipping downlink", correlation_id=ran_downlink.correlation_id
            )

    async def run(self, stop_event: asyncio.Event):
        downlink_topic = "down"
        await self.mqtt_client.subscribe(downlink_topic)
        async with self.mqtt_client.listen(downlink_topic) as downlink_queue:
            while not stop_event.is_set():
                try:
                    payload = None
                    with suppress(asyncio.TimeoutError):
                        _, payload = await asyncio.wait_for(downlink_queue.get(), 0.1)
                    if not payload:
                        continue

                    tti_downlink = tti_contracts.gatewayserver_pb2.GatewayDown()
                    tti_downlink.ParseFromString(payload)

                    logger.debug(
                        "Downlink message received from TTI",
                        tti_downlink=lazy_protobuf_fmt(tti_downlink),
                    )
                    await self._process_downlink(tti_downlink)

                except Exception:
                    logger.exception("Unhandled exception in in tti MQTT listening loop")
