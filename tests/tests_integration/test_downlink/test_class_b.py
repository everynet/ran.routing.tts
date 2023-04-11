import asyncio
import secrets

import pylorawan
import pytest
import tti_contracts

from lib.traffic.models import DownlinkDeviceContext, DownlinkResult, DownlinkResultStatus, DownlinkTiming

from ..conftest import TTiExtendedApi, TTITrafficRouter
from ..lorawan import UplinkMaker, decrypt_frm, generate_data_message, generate_join_request


@pytest.mark.skip(reason="test case not done yet")
@pytest.mark.integration
@pytest.mark.downstream
@pytest.mark.parametrize("device_otaa", [{"supports_class_c": False, "supports_class_b": True}], indirect=True)
async def test_otaa_class_b_downlink(
    tti_router: TTITrafficRouter,
    tti_api: TTiExtendedApi,
    device_otaa,
    make_uplink: UplinkMaker,
    gateway,
    gateway_heartbeat,  # Not used, but required (this fixture informs TTI about gateway alive state)  # noqa
):
    # TODO
    pass


@pytest.mark.skip(reason="test case not done yet")
@pytest.mark.integration
@pytest.mark.downstream
@pytest.mark.parametrize("device_abp", [{"supports_class_c": False, "supports_class_b": True}], indirect=True)
async def test_abp_class_b_downlink(
    tti_router: TTITrafficRouter,
    tti_api: TTiExtendedApi,
    device_abp,
    make_uplink: UplinkMaker,
    gateway,
    gateway_heartbeat,  # Not used, but required (this fixture informs TTI about gateway alive state)  # noqa
):
    # TODO
    pass
