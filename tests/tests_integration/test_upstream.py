import asyncio
import secrets

import pylorawan
import pytest

from lib.traffic.models import DownlinkDeviceContext, DownlinkResult, DownlinkResultStatus

from .conftest import TTITrafficRouter, TTiExtendedApi
from .lorawan import UplinkMaker, generate_data_message, generate_join_request


@pytest.mark.integration
@pytest.mark.upstream
async def test_abp_uplink(
    tti_router: TTITrafficRouter,
    device_abp,
    make_uplink: UplinkMaker,
):
    # Router must be synced before operations (because device may be added after creating router)
    await tti_router.force_sync()
    # Starting ran-router downstream listening loop
    stop = asyncio.Event()
    listener = asyncio.create_task(tti_router.run(stop))

    device = device_abp
    # Test uplink for joined device
    message = generate_data_message(
        # The device derives FNwkSIntKey & AppSKey from the NwkKey
        device.session.keys.app_s_key.key,
        device.session.keys.nwk_s_enc_key.key,
        device.session.dev_addr,
        secrets.token_bytes(6),
        confirmed=False,
        f_cnt=2,
    )
    uplink = make_uplink(message)

    uplink_ack = await tti_router.handle_upstream(uplink)
    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

    # # Printing packets (debug)
    # print(repr(uplink))
    # print(repr(uplink_ack))
    # print(repr(downlink))

    assert uplink.used_mic == uplink_ack.mic
    assert uplink.correlation_id == uplink_ack.correlation_id
    assert uplink_ack.dev_eui == device.ids.dev_eui

    assert uplink.correlation_id == downlink.correlation_id
    assert isinstance(downlink.device_ctx, DownlinkDeviceContext.Regular)
    assert downlink.device_ctx.dev_eui == device.ids.dev_eui
    assert downlink.device_ctx.target_dev_addr is None

    downlink_payload = pylorawan.message.PHYPayload.parse(downlink.payload)
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown
    assert downlink_payload.payload.fhdr.dev_addr == int.from_bytes(device.session.dev_addr, "big")

    # Terminating listener
    stop.set()
    await listener


@pytest.mark.integration
@pytest.mark.upstream
async def test_otaa_join(
    tti_router: TTITrafficRouter,
    device_otaa,
    make_uplink: UplinkMaker,
):
    # Router must be synced before operations (because device may be added after creating router)
    await tti_router.force_sync()
    # Starting ran-router downstream listening loop
    stop = asyncio.Event()
    listener = asyncio.create_task(tti_router.run(stop))

    device = device_otaa
    message = generate_join_request(
        device.root_keys.nwk_key.key,
        device.ids.join_eui,
        device.ids.dev_eui,
    )
    uplink = make_uplink(message)

    uplink_ack = await tti_router.handle_upstream(uplink)
    
    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

    # # Printing packets (debug)
    # print(repr(uplink))
    # print(repr(uplink_ack))
    # print(repr(downlink))

    assert uplink.used_mic == uplink_ack.mic
    assert uplink.correlation_id == uplink_ack.correlation_id
    assert uplink_ack.dev_eui == device.ids.dev_eui

    assert uplink.correlation_id == downlink.correlation_id
    assert isinstance(downlink.device_ctx, DownlinkDeviceContext.Regular)
    assert downlink.device_ctx.dev_eui == device.ids.dev_eui
    assert downlink.device_ctx.target_dev_addr is not None

    mhdr = pylorawan.message.MHDR.parse(downlink.payload[:1])
    assert mhdr.mtype == pylorawan.message.MType.JoinAccept

    join_accept_payload = pylorawan.message.JoinAccept.parse(downlink.payload, device.root_keys.nwk_key.key)
    assert join_accept_payload.dev_addr == int.from_bytes(downlink.device_ctx.target_dev_addr, "big")

    # Terminating listener
    stop.set()
    await listener



@pytest.mark.integration
@pytest.mark.upstream
async def test_otaa_join_and_uplink(
    tti_router: TTITrafficRouter,
    device_otaa,
    make_uplink: UplinkMaker,
    tti_api: TTiExtendedApi,
):
    # Router must be synced before operations (because device may be added after creating router)
    await tti_router.force_sync()
    # Starting ran-router downstream listening loop
    stop = asyncio.Event()
    listener = asyncio.create_task(tti_router.run(stop))

    device = device_otaa
    message = generate_join_request(
        device.root_keys.nwk_key.key,
        device.ids.join_eui,
        device.ids.dev_eui,
    )
    uplink = make_uplink(message)

    uplink_ack = await tti_router.handle_upstream(uplink)
    
    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

    # # Printing packets (debug)
    # print(repr(uplink))
    # print(repr(uplink_ack))
    # print(repr(downlink))

    assert uplink.used_mic == uplink_ack.mic
    assert uplink.correlation_id == uplink_ack.correlation_id
    assert uplink_ack.dev_eui == device.ids.dev_eui

    assert uplink.correlation_id == downlink.correlation_id
    assert isinstance(downlink.device_ctx, DownlinkDeviceContext.Regular)
    assert downlink.device_ctx.dev_eui == device.ids.dev_eui
    assert downlink.device_ctx.target_dev_addr is not None

    mhdr = pylorawan.message.MHDR.parse(downlink.payload[:1])
    assert mhdr.mtype == pylorawan.message.MType.JoinAccept

    join_accept_payload = pylorawan.message.JoinAccept.parse(downlink.payload, device.root_keys.nwk_key.key)
    assert join_accept_payload.dev_addr == int.from_bytes(downlink.device_ctx.target_dev_addr, "big")
    
    # Phase 2
    
    ns_data = await tti_api.get_device_ns_data(device.ids)
    # print("NS data:", ns_data)
    # Test uplink for joined device
    message = generate_data_message(
        # The device derives FNwkSIntKey & AppSKey from the NwkKey
        ns_data.pending_session.keys.f_nwk_s_int_key.key,
        ns_data.pending_session.keys.nwk_s_enc_key.key,
        ns_data.pending_session.dev_addr,
        secrets.token_bytes(6),
        confirmed=False,
        f_cnt=1,
    )
    uplink = make_uplink(message)

    uplink_ack = await tti_router.handle_upstream(uplink)
    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

    # # Printing packets (debug)
    # print(repr(uplink))
    # print(repr(uplink_ack))
    # print(repr(downlink))

    assert uplink.used_mic == uplink_ack.mic
    assert uplink.correlation_id == uplink_ack.correlation_id
    assert uplink_ack.dev_eui == device.ids.dev_eui

    assert uplink.correlation_id == downlink.correlation_id
    assert isinstance(downlink.device_ctx, DownlinkDeviceContext.Regular)
    assert downlink.device_ctx.dev_eui == device.ids.dev_eui
    assert downlink.device_ctx.target_dev_addr is None

    downlink_payload = pylorawan.message.PHYPayload.parse(downlink.payload)
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown

    assert downlink_payload.payload.fhdr.dev_addr == int.from_bytes(ns_data.pending_session.dev_addr, "big")

    # Terminating listener
    stop.set()
    await listener
