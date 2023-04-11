import asyncio
import secrets

import pylorawan
import pytest

from lib.traffic.models import DownlinkDeviceContext, DownlinkResult, DownlinkResultStatus, DownlinkTiming

from ..conftest import TTiExtendedApi, TTITrafficRouter
from ..lorawan import UplinkMaker, decrypt_frm, generate_data_message, generate_join_request


# @pytest.mark.skip(reason="test case not done yet")
@pytest.mark.integration
@pytest.mark.downstream
@pytest.mark.parametrize("device_abp", [{"supports_class_c": False, "supports_class_b": False}], indirect=True)
async def test_abp_class_a_downlink(
    tti_router: TTITrafficRouter,
    device_abp,
    make_uplink: UplinkMaker,
    gateway_heartbeat,  # Not used, but required (this fixture informs TTI about gateway alive state)  # noqa
):
    # Router must be synced before operations (because device may be added after creating router)
    await tti_router.force_sync()
    # Starting ran-router downstream listening loop
    stop = asyncio.Event()
    listener = asyncio.create_task(tti_router.run(stop))

    device = device_abp

    f_cnt = 2
    # Test uplink for joined device
    message = generate_data_message(
        # The device derives FNwkSIntKey & AppSKey from the NwkKey
        device.session.keys.app_s_key.key,
        device.session.keys.nwk_s_enc_key.key,
        device.session.dev_addr,
        secrets.token_bytes(6),
        confirmed=False,
        f_cnt=f_cnt,
    )
    uplink = make_uplink(message)
    uplink_ack = await tti_router.handle_upstream(uplink)

    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

    assert uplink.used_mic == uplink_ack.mic
    assert uplink.correlation_id == uplink_ack.correlation_id
    assert uplink_ack.dev_eui == device.ids.dev_eui

    assert uplink.correlation_id == downlink.correlation_id
    assert isinstance(downlink.device_ctx, DownlinkDeviceContext.Regular)
    assert isinstance(downlink.timing, DownlinkTiming.Delay)
    assert downlink.device_ctx.dev_eui == device.ids.dev_eui
    assert downlink.device_ctx.target_dev_addr is None

    # FIXME: After first uplink, TTI will send DevStatusReq, and we need to simulate
    #   DevStatusAns, before enqueuing real downlink, so here we just testing for received DevStatusReq without real
    #   downlink enqueued
    downlink_payload = pylorawan.message.PHYPayload.parse(downlink.payload)
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown
    assert downlink_payload.payload.fhdr.dev_addr == int.from_bytes(device.session.dev_addr, "big")
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown
    assert downlink_payload.payload.f_port == 0
    assert pylorawan.common.verify_mic_phy_payload(downlink_payload, device.session.keys.nwk_s_enc_key.key)

    # Terminating listener
    stop.set()
    await listener


@pytest.mark.integration
@pytest.mark.downstream
@pytest.mark.parametrize("device_otaa", [{"supports_class_c": False, "supports_class_b": False}], indirect=True)
async def test_otaa_class_a_downlink(
    tti_router: TTITrafficRouter,
    tti_api: TTiExtendedApi,
    device_otaa,
    make_uplink: UplinkMaker,
    gateway,
    gateway_heartbeat,  # Not used, but required (this fixture informs TTI about gateway alive state)  # noqa
):
    # Router must be synced before operations (because device may be added after creating router)
    await tti_router.force_sync()
    # Starting ran-router downstream listening loop
    stop = asyncio.Event()
    listener = asyncio.create_task(tti_router.run(stop))
    device = device_otaa

    # Phase 1 - Perform join
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

    # Phase 2 - enqueue downlink for device
    f_port = 2
    frm_payload = b"helloworld"
    await tti_api.enqueue_downlink(
        device_ids=device.ids,
        confirmed=False,
        frm_payload=frm_payload,
        f_port=f_port,
    )

    # Phase 3 - Send uplink for newly joined device, want to receive data downlink
    f_cnt = 2
    ns_data = await tti_api.get_device_ns_data(device.ids)
    # Sending uplink for joined device
    message = generate_data_message(
        # The device derives FNwkSIntKey & AppSKey from the NwkKey
        ns_data.pending_session.keys.f_nwk_s_int_key.key,
        ns_data.pending_session.keys.nwk_s_enc_key.key,
        ns_data.pending_session.dev_addr,
        b"data",
        confirmed=True,
        f_cnt=f_cnt,
    )
    uplink = make_uplink(message)
    uplink_ack = await tti_router.handle_upstream(uplink)

    # Receive downlink and ensure all things are OK
    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

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

    # We need to update device session info to verify encryption
    as_data = await tti_api.get_as_device_data(ns_data.ids)
    ns_data = await tti_api.get_device_ns_data(device.ids)
    assert pylorawan.common.verify_mic_phy_payload(downlink_payload, ns_data.session.keys.nwk_s_enc_key.key)
    assert (
        decrypt_frm(
            downlink_payload.payload.frm_payload,
            as_data.session.keys.app_s_key.key,
            downlink_payload.payload.fhdr.dev_addr,
            downlink_payload.payload.fhdr.f_cnt,
            1,
        )
        == frm_payload
    )

    # Terminating listener
    stop.set()
    await listener
