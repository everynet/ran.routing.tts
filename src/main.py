import signal
import sys
from contextlib import suppress

import structlog
from ran.routing.core import Core as RANCore

import settings
from lib.healthcheck import HealthcheckServer
from lib.logging_conf import configure_logging
from lib.mqtt import MQTTClient
from lib.ran_hook import RanSyncHook
from lib.traffic.manager import TrafficManager
from lib.traffic.ran import RanTrafficRouter
from lib.traffic.tti import TTIStatusUpdater, TTITrafficRouter
from lib.tti.api import TTIApi
from lib.tti.devices import MultiApplicationDeviceList
from lib.utils import Periodic

STOP_SIGNALS = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)

logger = structlog.getLogger(__name__)


async def healthcheck_live(context):
    pass


async def healthcheck_ready(context):
    pass


async def main(loop):
    configure_logging(
        log_level=settings.BRIDGE_LOG_LEVEL,
        console_colors=settings.BRIDGE_LOG_COLORS,
        json=settings.BRIDGE_LOG_JSON,
    )
    tags = settings.get_tags(settings.BRIDGE_DEVICE_MATCH_TAGS)
    logger.info("Device attribute object selector: ", tags=tags)

    tti_api = TTIApi.from_conn_params(
        host=settings.TTI_GRPC_API_HOST,
        port=settings.TTI_GRPC_API_PORT,
        secure=settings.TTI_GRPC_API_SECURE,
        cert_path=settings.TTI_GRPC_API_CERT_PATH,
        access_token=settings.TTI_GRPC_API_TOKEN,
    )

    tasks = set()

    stop_event = asyncio.Event()

    def stop_all() -> None:
        stop_event.set()
        logger.warning("Shutting down service! Press ^C again to terminate")

        def terminate():
            sys.exit("\nTerminated!\n")

        for sig in STOP_SIGNALS:
            loop.remove_signal_handler(sig)
            loop.add_signal_handler(sig, terminate)

    for sig in STOP_SIGNALS:
        loop.add_signal_handler(sig, stop_all)

    # TODO: better way to configure mqtt client
    if settings.TTI_TENANT_ID is not None:
        mqtt_username = f"{settings.TTI_GATEWAY_ID}@{settings.TTI_TENANT_ID}"
        logger.info("Using MQTT username for multi-tenant env", mqtt_username=mqtt_username)
    else:
        mqtt_username = settings.TTI_GATEWAY_ID

    mqtt = MQTTClient.from_conn_params(
        host=settings.TTI_GW_MQTT_HOST,
        port=settings.TTI_GW_MQTT_PORT,
        username=mqtt_username,
        password=settings.TTI_GW_MQTT_TOKEN,
        topics_prefix=f"v3/{mqtt_username}",
        secure=settings.TTI_GW_MQTT_SECURE,
        cert_path=settings.TTI_GW_MQTT_CERT_PATH,
    )
    tasks.add(asyncio.create_task(mqtt.run(stop_event), name="mqtt_client"))
    mqtt_connect_timeout = 15  # seconds
    if not await mqtt.wait_for_connection(timeout=mqtt_connect_timeout):
        logger.error(f"MQTT client not connected after {mqtt_connect_timeout}s.")
        return
    logger.info("MQTT client started", task_name="mqtt_client")

    ran_core = RANCore(access_token=settings.RAN_API_TOKEN, url=settings.RAN_API_URL)
    await ran_core.connect()

    logger.info("Cleanup RAN device list")
    await ran_core.routing_table.delete_all()
    logger.info("Cleanup done")

    devices_list = MultiApplicationDeviceList(tti=tti_api, update_hook=RanSyncHook(ran_core), tags=tags)

    logger.info("Performing initial TTI devices list sync")
    await devices_list.sync_from_remote()
    logger.info("Devices synced")
    tasks.add(
        Periodic(devices_list.sync_from_remote).create_task(
            stop_event,
            interval=20.0,
            task_name="update_tti_device_list",
        )
    )
    logger.info("Periodic devices list sync scheduled", task_name="update_tti_device_list")

    status_updater = TTIStatusUpdater(mqtt)
    # initial status submit
    await status_updater.submit_initial_status()
    tasks.add(
        Periodic(status_updater.submit_status).create_task(
            stop_event,
            interval=60.0,
            task_name="status_updater",
        ),
    )
    logger.info("Periodic status updating scheduled", task_name="status_updater")

    tti_router = TTITrafficRouter(settings.TTI_GATEWAY_ID, mqtt_client=mqtt, devices=devices_list)
    tasks.add(asyncio.create_task(tti_router.run(stop_event), name="tti_traffic_router"))
    logger.info("TTI traffic router started", task_name="tti_traffic_router")

    ran_router = RanTrafficRouter(ran_core)
    tasks.add(asyncio.create_task(ran_router.run(stop_event), name="ran_traffic_router"))
    logger.info("Ran traffic router started", task_name="ran_traffic_router")

    manager = TrafficManager(tti=tti_router, ran=ran_router)
    tasks.add(asyncio.create_task(manager.run(stop_event), name="traffic_manager"))
    logger.info("TrafficManager started", task_name="traffic_manager")

    healthcheck_server = HealthcheckServer(
        live_handler=healthcheck_live,
        ready_handler=healthcheck_ready,
        context=None,
    )
    tasks.add(
        asyncio.create_task(
            healthcheck_server.run(
                stop_event,
                settings.BRIDGE_HEALTHCHECK_SERVER_HOST,
                settings.BRIDGE_HEALTHCHECK_SERVER_PORT,
            ),
            name="health_check",
        )
    )
    logger.info("HealthCheck server started", task_name="health_check")

    tasks.add(asyncio.create_task(stop_event.wait(), name="stop_event_wait"))

    finished, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finished_task = finished.pop()
    logger.warning(f"Task {finished_task.get_name()!r} exited, shutting down gracefully")

    graceful_shutdown_max_time = 20  # seconds
    for task in pending:
        with suppress(asyncio.TimeoutError):
            logger.debug(f"Waiting task {task.get_name()!r} to shutdown gracefully")
            await asyncio.wait_for(task, graceful_shutdown_max_time / len(tasks))
            logger.debug(f"Task {task.get_name()!r} exited")

    # If tasks not exited gracefully, terminate them by cancelling
    for task in pending:
        if not task.done():
            task.cancel()

    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            logger.warning(f"Task {task.get_name()!r} terminated")

    logger.info("Bye!")


if __name__ == "__main__":
    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(main(loop))
