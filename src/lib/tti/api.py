import asyncio
from itertools import count
from operator import attrgetter
from typing import AsyncIterator, Optional, Union

import grpc
import structlog
import tti_contracts
from google.protobuf.field_mask_pb2 import FieldMask
from yarl import URL

from .models import DeviceIdentifiers

logger = structlog.getLogger(__name__)

AppId = Union[str, tti_contracts.identifiers_pb2.ApplicationIdentifiers]
DevId = Union[DeviceIdentifiers, tti_contracts.identifiers_pb2.EndDeviceIdentifiers]


def suppress_rpc_error(codes: Optional[list] = None):
    codes = codes if codes is not None else []

    def wrapped(func):
        async def wrapped(*args, **kwargs):
            try:
                value = func(*args, **kwargs)
                if asyncio.iscoroutine(value):
                    return await value
                return value
            except grpc.aio.AioRpcError as e:
                if e.code() in codes:
                    return None
                raise e

        return wrapped

    return wrapped


def get_grpc_channel(host: str, port: str, secure: bool = True, cert_path: str | None = None) -> grpc.aio.Channel:
    target_addr = f"{host}:{port}"
    channel = None

    if secure:
        if cert_path is not None:
            with open(cert_path, "rb") as f:
                credentials = grpc.ssl_channel_credentials(f.read())
        else:
            credentials = grpc.ssl_channel_credentials()

        channel = grpc.aio.secure_channel(target_addr, credentials)
    else:
        channel = grpc.aio.insecure_channel(target_addr)

    return channel


def grpc_channel_from_url(url: str) -> grpc.aio.Channel:
    url_obj = URL(url)
    if url_obj.scheme.lower() not in ("http", "https"):
        raise Exception("Please, specify url schema  url")
    return get_grpc_channel(url_obj.host, url_obj.port, url_obj.scheme == "https", None)  # type: ignore


class TTIApiBase:
    def __init__(self, grpc_channel: grpc.aio.Channel, access_token: str) -> None:
        self._channel = grpc_channel
        self._access_token = access_token

    @property
    def _grpc_meta(self):
        if self._access_token is None:
            raise Exception("Not authenticated, please, specify access token for this api client")
        return [("authorization", f"Bearer {self._access_token}")]

    @classmethod
    def from_url(cls, url: str, access_token: str, **kwargs):
        url_obj = URL(url)
        if url_obj.scheme.lower() not in ("http", "https"):
            raise Exception("Please, specify url schema")
        return cls(grpc_channel=grpc_channel_from_url(url), access_token=access_token, **kwargs)

    @classmethod
    def from_conn_params(
        cls, host: str, port: str, access_token: str, secure: bool = True, cert_path: Optional[str] = None, **kwargs
    ):
        return cls(grpc_channel=get_grpc_channel(host, port, secure, cert_path), access_token=access_token, **kwargs)

    async def _paginate(self, method, request, items_field: str, page_size: int = 20):

        get_attr = attrgetter(items_field)
        page_cnt = count()
        next(page_cnt)

        for page in page_cnt:
            request.page = page
            request.limit = page_size
            response = await method(request, metadata=self._grpc_meta)

            result = get_attr(response)
            if not result:
                break
            for item in result:
                yield item

    @staticmethod
    def _wrap_app_id(app_id: AppId) -> tti_contracts.identifiers_pb2.ApplicationIdentifiers:
        if isinstance(app_id, str):
            return tti_contracts.identifiers_pb2.ApplicationIdentifiers(application_id=app_id)
        elif isinstance(app_id, tti_contracts.identifiers_pb2.ApplicationIdentifiers):
            return app_id
        else:
            raise ValueError(f"Unsupported AppId type: {type(app_id)}")

    @staticmethod
    def _wrap_dev_id(dev_id: DevId) -> tti_contracts.identifiers_pb2.EndDeviceIdentifiers:
        if isinstance(dev_id, DeviceIdentifiers):
            return dev_id.as_pb2()
        elif isinstance(dev_id, tti_contracts.identifiers_pb2.EndDeviceIdentifiers):
            return dev_id
        else:
            raise ValueError(f"Unsupported DevId type: {type(dev_id)}")


class TTIApplicationApi(TTIApiBase):
    def __init__(self, app_id: str, grpc_channel: grpc.aio.Channel, access_token: str) -> None:
        super().__init__(grpc_channel, access_token)
        if not isinstance(app_id, tti_contracts.identifiers_pb2.ApplicationIdentifiers):
            app_id = tti_contracts.identifiers_pb2.ApplicationIdentifiers(application_id=app_id)
        self._app_id = app_id

    # async def list_keys(self, app_id):
    #     service = tti_contracts.application_services_pb2_grpc.ApplicationAccessStub(self._channel)
    #     req = tti_contracts.application_pb2.ListApplicationAPIKeysRequest()
    #     req.application_ids.MergeFrom(app_id)

    #     return await service.ListAPIKeys(req)

    # async def rights(self, app_id):
    #     service = tti_contracts.application_services_pb2_grpc.ApplicationAccessStub(self._channel)
    #     if not isinstance(app_id, tti_contracts.identifiers_pb2.ApplicationIdentifiers):
    #         app_id = tti_contracts.identifiers_pb2.ApplicationIdentifiers(application_id=app_id)

    #     return await service.ListRights(app_id)

    async def list_devices(self) -> AsyncIterator[tti_contracts.end_device_pb2.EndDevice]:
        service = tti_contracts.end_device_services_pb2_grpc.EndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.ListEndDevicesRequest()
        req.application_ids.MergeFrom(self._app_id)
        req.field_mask.MergeFrom(FieldMask(paths=["attributes"]))

        async for end_device in self._paginate(service.List, req, "end_devices"):
            yield end_device

    async def get_device(self, dev_id):
        service = tti_contracts.end_device_services_pb2_grpc.EndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

        req.end_device_ids.MergeFrom(dev_id)
        req.field_mask.MergeFrom(FieldMask(paths=["attributes"]))

        return await service.Get(req, metadata=self._grpc_meta)

    @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    async def get_root_keys(self, dev_id):
        service = tti_contracts.joinserver_pb2_grpc.JsEndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

        req.end_device_ids.MergeFrom(dev_id)
        req.field_mask.MergeFrom(FieldMask(paths=["root_keys"]))

        return (await service.Get(req, metadata=self._grpc_meta)).root_keys

    @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    async def get_as_keys(self, dev_id):
        service = tti_contracts.applicationserver_pb2_grpc.AsEndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

        req.end_device_ids.MergeFrom(dev_id)
        req.field_mask.MergeFrom(FieldMask(paths=["session.keys"]))
        return (await service.Get(req, metadata=self._grpc_meta)).session.keys

    @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    async def get_ns_keys(self, dev_id):
        service = tti_contracts.networkserver_pb2_grpc.NsEndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

        req.end_device_ids.MergeFrom(dev_id)
        req.field_mask.MergeFrom(FieldMask(paths=["session.keys"]))
        return (await service.Get(req, metadata=self._grpc_meta)).session.keys


class TTIApi(TTIApiBase):
    async def list_applications(self):
        service = tti_contracts.application_services_pb2_grpc.ApplicationRegistryStub(self._channel)
        req = tti_contracts.application_pb2.ListApplicationsRequest()

        async for api_key in self._paginate(service.List, req, "applications"):
            yield api_key

    # async def rights(self, app_id: AppId):
    #     service = tti_contracts.application_services_pb2_grpc.ApplicationAccessStub(self._channel)
    #     return await service.ListRights(self._wrap_app_id(app_id))

    # async def gw(self, gateway_id: str):
    #     service = tti_contracts.gatewayserver_pb2_grpc.GtwGsStub(self._channel)
    #     req = tti_contracts.identifiers_pb2.GatewayIdentifiers(gateway_id=gateway_id)

    #     # print(await service.GetConcentratorConfig(Empty()))

    #     return await service.GetMQTTConnectionInfo(req, metadata=self._grpc_meta)

    async def list_devices(self, app_id: AppId) -> AsyncIterator[tti_contracts.end_device_pb2.EndDevice]:
        service = tti_contracts.end_device_services_pb2_grpc.EndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.ListEndDevicesRequest()

        req.application_ids.MergeFrom(self._wrap_app_id(app_id))
        req.field_mask.MergeFrom(FieldMask(paths=["attributes", "updated_at"]))

        async for end_device in self._paginate(service.List, req, "end_devices"):
            yield end_device

    async def get_device_ns_data(self, dev_id: DevId) -> tti_contracts.end_device_pb2.EndDevice:
        service = tti_contracts.networkserver_pb2_grpc.NsEndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

        req.end_device_ids.MergeFrom(self._wrap_dev_id(dev_id))
        req.field_mask.MergeFrom(
            FieldMask(
                paths=[
                    "multicast",
                    # "supports_class_b",
                    # "supports_class_c",
                    # "supports_join",
                    # "mac_state",
                    # "mac_settings",
                    "session",
                    "pending_session",
                ]
            )
        )
        return await service.Get(req, metadata=self._grpc_meta)

    # async def get_end_device_data(self, dev_id):
    #     service = tti_contracts.end_device_services_pb2_grpc.EndDeviceRegistryStub(self._channel)
    #     req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

    #     req.end_device_ids.MergeFrom(dev_id)
    #     req.field_mask.MergeFrom(FieldMask(paths=["attributes"]))

    #     return await service.Get(req, metadata=self._grpc_meta)

    @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    async def get_js_device_keys(self, dev_id: DevId):
        service = tti_contracts.joinserver_pb2_grpc.JsEndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

        req.end_device_ids.MergeFrom(self._wrap_dev_id(dev_id))
        req.field_mask.MergeFrom(FieldMask(paths=["root_keys"]))

        return (await service.Get(req, metadata=self._grpc_meta)).root_keys

    # @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    # async def get_end_device_data(self, dev_id: DevId):
    #     service = tti_contracts.applicationserver_pb2_grpc.AsEndDeviceRegistryStub(self._channel)
    #     req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

    #     req.end_device_ids.MergeFrom(self._wrap_dev_id(dev_id))
    #     # req.field_mask.MergeFrom(FieldMask(paths=["session.keys", "session.dev_addr"]))
    #     return await service.Get(req, metadata=self._grpc_meta)

    # @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    # async def get_as_device_data(self, dev_id: DevId):
    #     service = tti_contracts.applicationserver_pb2_grpc.AsEndDeviceRegistryStub(self._channel)
    #     req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

    #     req.end_device_ids.MergeFrom(self._wrap_dev_id(dev_id))
    #     req.field_mask.MergeFrom(FieldMask(paths=["session.keys", "session.dev_addr"]))
    #     return await service.Get(req, metadata=self._grpc_meta)

    # @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    # async def get_as_device_keys(self, dev_id: DevId):
    #     service = tti_contracts.applicationserver_pb2_grpc.AsEndDeviceRegistryStub(self._channel)
    #     req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

    #     req.end_device_ids.MergeFrom(self._wrap_dev_id(dev_id))
    #     req.field_mask.MergeFrom(FieldMask(paths=["session.keys"]))
    #     return (await service.Get(req, metadata=self._grpc_meta)).session.keys

    # @suppress_rpc_error([grpc.StatusCode.NOT_FOUND])
    # async def get_ns_device_keys(self, dev_id):
    #     service = tti_contracts.networkserver_pb2_grpc.NsEndDeviceRegistryStub(self._channel)
    #     req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

    #     req.end_device_ids.MergeFrom(dev_id)
    #     req.field_mask.MergeFrom(FieldMask(paths=["session.keys"]))
    #     return (await service.Get(req, metadata=self._grpc_meta)).session.keys
