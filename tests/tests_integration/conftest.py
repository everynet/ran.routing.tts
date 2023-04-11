import asyncio
import secrets
from typing import Any

import pytest
import tti_contracts

from lib.mqtt import MQTTClient
from lib.traffic.tti import TTIStatusUpdater, TTITrafficRouter
from lib.tti.devices import ApplicationDeviceList
from lib.utils import Periodic

from .ext_tti_api import TTiExtendedApi
from .lorawan import make_uplink  # required fixture  # noqa


@pytest.fixture(
    params=[
        "eu868",
        # Uncomment other regions, when channels tests added
        # "us915",
        # "as923",
        # "as923_2",
        # "us915",
        # "us915_a",
        # "au915_a",
    ]
)
def current_region(request) -> str:
    return request.param


REGION_CONFIGS: dict[str, Any] = {
    "eu868": {
        "frequency_plan": "EU_863_870",
        "region_name": "eu868",
        "uplink": dict(spreading=12, bandwidth=125000, frequency=868100000),
        # "uplink": dict(spreading=12, bandwidth=125000, frequency=867100000),
        "multicast": dict(dr=0, frequency=869525000),
    },
    # "as923": {
    #     "region_name": "as923",
    #     "region_topic": "as923",
    #     "region_common_name": "AS923",
    #     "uplink": dict(spreading=12, bandwidth=125000, frequency=923200000),
    #     "multicast": dict(dr=2, frequency=923200000),
    # },
    # "as923_2": {
    #     "region_name": "as923_2",
    #     "region_topic": "as923_2",
    #     "region_common_name": "AS923_2",
    #     "uplink": dict(spreading=12, bandwidth=125000, frequency=921400000),
    #     "multicast": dict(dr=0, frequency=921400000),
    # },
    # "us915": {
    #     "region_name": "us915",
    #     "region_topic": "us915",
    #     "region_common_name": "US915",
    #     "uplink": dict(spreading=10, bandwidth=125000, frequency=906300000),
    #     "multicast": dict(dr=8, frequency=923300000),
    # },
    # "us915_a": {
    #     "region_name": "us915_a",
    #     "region_topic": "us915_a",
    #     "region_common_name": "US915",
    #     "uplink": dict(spreading=10, bandwidth=125000, frequency=902300000),
    #     "multicast": dict(dr=8, frequency=923300000),
    # },
    # "au915_a": {
    #     "region_name": "au915_a",
    #     "region_topic": "au915_a",
    #     "region_common_name": "AU915",
    #     "uplink": dict(spreading=12, bandwidth=125000, frequency=915200000),
    #     "multicast": dict(dr=2, frequency=923200000),
    # },
}


@pytest.fixture
def region_params(current_region) -> dict[str, Any]:
    return REGION_CONFIGS[current_region]


@pytest.fixture
def api_token() -> str:
    from lib.environs import Env

    env = Env()
    env.read_env()

    var_name = "TTI_GRPC_API_TOKEN"
    if not (token := env(var_name)):
        pytest.exit(f"Integration tests failed (env var {var_name} not set)")
    return token


@pytest.fixture
def user_id() -> str:
    return "admin"


@pytest.fixture
async def tti_api(api_token) -> TTiExtendedApi:
    try:
        tti_api = TTiExtendedApi.from_url("http://localhost:1885/", access_token=api_token)
    except Exception as e:
        return pytest.exit(f"Could not connect to grpc api: {e}")
    return tti_api


@pytest.fixture(scope="function")
async def application(tti_api: TTiExtendedApi, user_id):
    app = await tti_api.create_application("pytest-test-app", user_id=user_id, app_id="pytest-test-app")

    try:
        yield app
    finally:
        await tti_api.purge_application(app.ids)


@pytest.fixture(scope="function")
async def gateway(tti_api: TTiExtendedApi, user_id, region_params):
    gw = await tti_api.create_gateway(
        gateway_id="pytest-test-gw",
        eui=b"00000001",
        name="pytest-test-gw",
        frequency_plans=[region_params["frequency_plan"]],
        user_id=user_id,
    )

    yield gw

    await tti_api.purge_gateway(gw.ids)


@pytest.fixture(scope="function")
async def gateway_api_key(tti_api: TTiExtendedApi, gateway):
    gw = await tti_api.create_gateway_key(gateway.ids)

    yield gw

    # Will be deleted after gateway was purged, todo: add key removing.


@pytest.fixture(scope="function")
async def device_abp(request, tti_api: TTiExtendedApi, application, region_params):

    if not (param := getattr(request, "param", None)):
        param = {"supports_class_c": False, "supports_class_b": False}

    dev_addr = secrets.token_bytes(4)
    dev_eui = secrets.token_bytes(8)
    # dev_id_str = "pytest-dev-abp"
    dev_id_str = f"pytest-dev-abp-{dev_eui.hex()}"
    Key = tti_contracts.keys_pb2.KeyEnvelope

    ids = tti_contracts.identifiers_pb2.EndDeviceIdentifiers(
        device_id=dev_id_str,
        application_ids=application.ids,
        dev_eui=dev_eui,
        dev_addr=dev_addr,
        join_eui=secrets.token_bytes(8),
    )
    nwk_key = secrets.token_bytes(16)
    root_keys = tti_contracts.keys_pb2.RootKeys(
        root_key_id=f"root-keys-{dev_id_str}",
        app_key=Key(key=nwk_key),
        nwk_key=Key(key=nwk_key),
    )

    nkw_s_key = secrets.token_bytes(16)
    session = tti_contracts.end_device_pb2.Session(
        dev_addr=dev_addr,
        keys=tti_contracts.keys_pb2.SessionKeys(
            session_key_id=f"session-keys-{dev_id_str}".encode(),
            f_nwk_s_int_key=Key(key=nkw_s_key),
            s_nwk_s_int_key=Key(key=nkw_s_key),
            nwk_s_enc_key=Key(key=nkw_s_key),
            app_s_key=Key(key=secrets.token_bytes(16)),
        ),
    )

    params = dict(
        ids=ids,
        name=dev_id_str,
        root_keys=root_keys,
        session=session,
        supports_class_b=param.get("supports_class_b"),
        supports_class_c=param.get("supports_class_c"),
        frequency_plan_id=region_params["frequency_plan"],
    )
    await tti_api.create_device(**params)
    await tti_api.create_ns_device_abp(**params)
    await tti_api.create_as_device(**params)

    yield tti_api.assemble_device_pb2(**params)

    await tti_api.delete_device(ids)


@pytest.fixture(scope="function")
async def device_otaa(request, tti_api: TTiExtendedApi, application, region_params):

    if not (param := getattr(request, "param", None)):
        param = {"supports_class_c": False, "supports_class_b": False}

    dev_eui = secrets.token_bytes(8)
    # dev_id_str = "pytest-dev-otaa"
    dev_id_str = f"pytest-dev-otaa-{dev_eui.hex()}"
    Key = tti_contracts.keys_pb2.KeyEnvelope

    ids = tti_contracts.identifiers_pb2.EndDeviceIdentifiers(
        device_id=dev_id_str,
        application_ids=application.ids,
        dev_eui=dev_eui,
        join_eui=secrets.token_bytes(8),
    )
    nwk_key = secrets.token_bytes(16)
    root_keys = tti_contracts.keys_pb2.RootKeys(
        root_key_id=f"root-keys-{dev_id_str}",
        app_key=Key(key=nwk_key),
        nwk_key=Key(key=nwk_key),
    )

    session = tti_contracts.end_device_pb2.Session(
        keys=tti_contracts.keys_pb2.SessionKeys(
            session_key_id=f"session-keys-{dev_id_str}".encode(),
            app_s_key=Key(key=secrets.token_bytes(16)),
        ),
    )

    params = dict(
        session=session,
        ids=ids,
        name=dev_id_str,
        root_keys=root_keys,
        frequency_plan_id=region_params["frequency_plan"],
        supports_join=True,
        supports_class_b=param.get("supports_class_b"),
        supports_class_c=param.get("supports_class_c"),
    )
    await tti_api.create_device(**params)
    try:
        ns_info = await tti_api.create_ns_device_otaa(**params)
        params["ids"].dev_eui = ns_info.ids.dev_eui
        params["ids"].join_eui = ns_info.ids.join_eui
        await tti_api.create_js_device(**params)
        await tti_api.create_as_device(has_dev_addr=False, **params)
        yield tti_api.assemble_device_pb2(**params)
    finally:
        await tti_api.delete_device(ids)


@pytest.fixture
async def mqtt_client(gateway_api_key, gateway) -> MQTTClient:
    client = MQTTClient.from_conn_params(
        host="localhost",
        port=1882,
        username=gateway.ids.gateway_id,
        password=gateway_api_key.key,
        topics_prefix=f"v3/{gateway.ids.gateway_id}",
    )
    stop = asyncio.Event()
    stop.clear()

    client_task = asyncio.create_task(client.run(stop))

    await client.wait_for_connection()
    yield client

    stop.set()
    await client_task


@pytest.fixture
async def gateway_heartbeat(mqtt_client: MQTTClient):
    updater = TTIStatusUpdater(mqtt_client)
    await updater.submit_initial_status()

    stop = asyncio.Event()
    task = Periodic(updater.submit_status).create_task(stop_event=stop, interval=10, task_name="gw_heartbeat")

    try:
        yield
    finally:
        stop.set()
        await task


@pytest.fixture
async def tti_router(tti_api: TTiExtendedApi, mqtt_client: MQTTClient, gateway, application):
    # devices = ApplicationDeviceList(tti_api, application_id=application.ids.application_id, tags={"ran": "yes"})
    devices = ApplicationDeviceList(tti_api, application_id=application.ids.application_id)
    await devices.sync_from_remote()

    # multicast_groups = ApplicationMulticastGroupList(chirpstack_api, application_id=app_id, tenant_id=tenant_id)
    # await multicast_groups.sync_from_remote()

    tti_router = TTITrafficRouter(
        gateway_id=gateway.ids.gateway_id,
        mqtt_client=mqtt_client,
        devices=devices,
        # multicast_groups=multicast_groups,
    )

    async def force_sync():
        await devices.sync_from_remote()
        # await multicast_groups.sync_from_remote()

    # This is extra method, which can be used to sync devices/multicast groups from tti without periodic update
    tti_router.force_sync = force_sync

    yield tti_router
