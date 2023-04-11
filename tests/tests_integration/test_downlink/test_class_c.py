import asyncio
import secrets

import pylorawan
import pytest
import tti_contracts

from lib.traffic.models import DownlinkDeviceContext, DownlinkResult, DownlinkResultStatus, DownlinkTiming

from ..conftest import TTiExtendedApi, TTITrafficRouter
from ..lorawan import UplinkMaker, decrypt_frm, generate_data_message, generate_join_request


@pytest.mark.integration
@pytest.mark.downstream
@pytest.mark.parametrize("device_abp", [{"supports_class_c": True, "supports_class_b": False}], indirect=True)
async def test_abp_class_c_downlink(
    tti_router: TTITrafficRouter,
    tti_api: TTiExtendedApi,
    device_abp,
    make_uplink: UplinkMaker,
    gateway,
    gateway_heartbeat,  # Not used, but required (this fixture informs TTI about gateway alive state)  # noqa
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
        confirmed=True,
        f_cnt=2,
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
    assert downlink.device_ctx.target_dev_addr is None

    downlink_payload = pylorawan.message.PHYPayload.parse(downlink.payload)
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown
    assert downlink_payload.payload.fhdr.dev_addr == int.from_bytes(device.session.dev_addr, "big")

    f_port = 2
    frm_payload = b"helloworld"
    gw_info = tti_contracts.lorawan_pb2.ClassBCGatewayIdentifiers()
    gw_info.gateway_ids.MergeFrom(gateway.ids)
    class_b_c = tti_contracts.messages_pb2.ApplicationDownlink.ClassBC()
    class_b_c.gateways.append(gw_info)
    await tti_api.enqueue_downlink(
        device_ids=device.ids,
        confirmed=False,
        frm_payload=frm_payload,
        f_port=f_port,
        class_b_c=class_b_c,
    )
    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

    assert isinstance(downlink.timing, DownlinkTiming.Immediately)
    assert downlink.device_ctx.dev_eui == device.ids.dev_eui
    downlink_payload = pylorawan.message.PHYPayload.parse(downlink.payload)
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown
    assert downlink_payload.payload.f_port == f_port
    assert downlink_payload.payload.fhdr.dev_addr == int.from_bytes(device.session.dev_addr, "big")
    assert pylorawan.common.verify_mic_phy_payload(downlink_payload, device.session.keys.nwk_s_enc_key.key)
    assert (
        decrypt_frm(
            downlink_payload.payload.frm_payload,
            device.session.keys.app_s_key.key,
            downlink_payload.payload.fhdr.dev_addr,
            downlink_payload.payload.fhdr.f_cnt,
            1,
        )
        == frm_payload
    )

    # Terminating listener
    stop.set()
    await listener


@pytest.mark.integration
@pytest.mark.downstream
@pytest.mark.parametrize("device_otaa", [{"supports_class_c": True, "supports_class_b": False}], indirect=True)
async def test_otaa_class_c_downlink(
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

    # Phase 2 - Send uplink for newly joined device
    ns_data = await tti_api.get_device_ns_data(device.ids)
    session = ns_data.pending_session
    # Test uplink for joined device
    f_cnt = 0
    message = generate_data_message(
        # The device derives FNwkSIntKey & AppSKey from the NwkKey
        session.keys.f_nwk_s_int_key.key,
        session.keys.nwk_s_enc_key.key,
        session.dev_addr,
        b"data",
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
    assert downlink.device_ctx.dev_eui == device.ids.dev_eui
    assert downlink.device_ctx.target_dev_addr is None

    downlink_payload = pylorawan.message.PHYPayload.parse(downlink.payload)
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown

    assert downlink_payload.payload.fhdr.dev_addr == int.from_bytes(ns_data.pending_session.dev_addr, "big")

    # Phase 3 - enqueue and send downlink for device
    ns_data = await tti_api.get_device_ns_data(device.ids)
    as_data = await tti_api.get_as_device_data(ns_data.ids)

    f_port = 2
    frm_payload = b"helloworld"
    gw_info = tti_contracts.lorawan_pb2.ClassBCGatewayIdentifiers()
    gw_info.gateway_ids.MergeFrom(gateway.ids)
    class_b_c = tti_contracts.messages_pb2.ApplicationDownlink.ClassBC()
    class_b_c.gateways.append(gw_info)

    await tti_api.enqueue_downlink(
        device_ids=ns_data.ids,
        confirmed=False,
        frm_payload=frm_payload,
        f_port=f_port,
        class_b_c=class_b_c,
    )

    # Phase 4 - Wait for downlink
    downlink = await tti_router.downstream_rx.get()
    await tti_router.handle_downstream_result(
        DownlinkResult(correlation_id=downlink.correlation_id, status=DownlinkResultStatus.OK)
    )

    assert isinstance(downlink.timing, DownlinkTiming.Immediately)
    assert downlink.device_ctx.dev_eui == ns_data.ids.dev_eui
    downlink_payload = pylorawan.message.PHYPayload.parse(downlink.payload)
    assert downlink_payload.mhdr.mtype == pylorawan.message.MType.UnconfirmedDataDown
    assert downlink_payload.payload.f_port == f_port
    assert downlink_payload.payload.fhdr.dev_addr == int.from_bytes(ns_data.session.dev_addr, "big")
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
