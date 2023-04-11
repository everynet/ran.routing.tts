import tti_contracts

from lib.tti.api import TTIApi, suppress_rpc_error, AppId
from google.protobuf.field_mask_pb2 import FieldMask


def make_str_id_as_pb2_wrap(pb_struct, field: str):
    def wrap(_, value):
        if isinstance(value, pb_struct):
            return value
        elif isinstance(value, str):
            return pb_struct(**{field: value})
        else:
            raise ValueError(f"Value {value!r} of type {type(value)!r} can't be converted into {pb_struct!r}")

    return wrap


# def make_str_id_as_pb2_wrap(pb_struct, fields: str | tuple[str, ...]):

#     if isinstance(fields, str):
#         fields = (fields,)

#     def wrap(*args, **kwargs):
#         args = args[1:]

#         if len(args) == 1 and isinstance(args[0], pb_struct):
#             return args[0]

#         struct_args = {}
#         for idx, field in enumerate(fields):
#             if val := kwargs.get(field, None):
#                 struct_args[field] = val
#             elif len(args) <= (idx + 1):
#                 val = args[idx]
#                 struct_args[field] = val
#             else:
#                 struct_args[field] = None

#         return pb_struct(**struct_args)

#     return wrap


class TTiExtendedApi(TTIApi):
    # _wrap_gw_id = make_str_id_as_pb2_wrap(tti_contracts.identifiers_pb2.GatewayIdentifiers, ("gateway_id", "eui"))
    _wrap_user_id = make_str_id_as_pb2_wrap(tti_contracts.identifiers_pb2.UserIdentifiers, "user_id")

    def _wrap_gw_id(self, gateway_id, eui: bytes | None = None):
        struct = tti_contracts.identifiers_pb2.GatewayIdentifiers

        if eui is not None:
            if not isinstance(gateway_id, str):
                raise ValueError("If 'eui' provided, 'gateway_ids' must be str")
            return struct(gateway_id=gateway_id, eui=eui)

        if isinstance(gateway_id, str):
            return struct(gateway_id=gateway_id)
        elif isinstance(gateway_id, struct):
            return gateway_id
        else:
            raise ValueError(f"Unknown 'gateway_id' type {type(gateway_id)}")

    def _wrap_user_as_collaborator(self, user_id):
        collaborator = tti_contracts.identifiers_pb2.OrganizationOrUserIdentifiers()
        collaborator.user_ids.MergeFrom(self._wrap_user_id(user_id))
        return collaborator

    async def create_application(self, name: str, user_id: str, app_id: str | None = None):
        service = tti_contracts.application_services_pb2_grpc.ApplicationRegistryStub(self._channel)

        application = tti_contracts.application_pb2.Application()
        application.name = name
        application.ids.MergeFrom(self._wrap_app_id(app_id or name))
        request = tti_contracts.application_pb2.CreateApplicationRequest()
        request.application.MergeFrom(application)
        request.collaborator.MergeFrom(self._wrap_user_as_collaborator(user_id))

        return await service.Create(request, metadata=self._grpc_meta)

    async def purge_application(self, app_id: AppId):
        service = tti_contracts.application_services_pb2_grpc.ApplicationRegistryStub(self._channel)

        return await service.Purge(self._wrap_app_id(app_id), metadata=self._grpc_meta)

    async def create_gateway(
        self,
        eui: bytes,
        name: str,
        user_id: str,
        frequency_plans: list[str],
        gateway_id: str | None = None,
    ):
        service = tti_contracts.gateway_services_pb2_grpc.GatewayRegistryStub(self._channel)

        gateway = tti_contracts.gateway_pb2.Gateway()
        gateway.ids.MergeFrom(self._wrap_gw_id(gateway_id=gateway_id or (eui.decode() + "-" + name), eui=eui))
        gateway.name = name
        for freq_plan in frequency_plans:
            gateway.frequency_plan_ids.append(freq_plan)
        gateway.require_authenticated_connection = False
        gateway.status_public = False
        gateway.location_public = False

        request = tti_contracts.gateway_pb2.CreateGatewayRequest()
        request.collaborator.MergeFrom(self._wrap_user_as_collaborator(user_id))
        request.gateway.MergeFrom(gateway)

        return await service.Create(request, metadata=self._grpc_meta)

    async def purge_gateway(self, gateway_id):
        service = tti_contracts.gateway_services_pb2_grpc.GatewayRegistryStub(self._channel)
        return await service.Purge(self._wrap_gw_id(gateway_id), metadata=self._grpc_meta)

    async def create_gateway_key(
        self,
        gateway_id,
        key_name: str | None = None,
        rights: tuple[str, ...] = ("RIGHT_ALL",),
    ):

        service = tti_contracts.gateway_services_pb2_grpc.GatewayAccessStub(self._channel)

        request = tti_contracts.gateway_pb2.CreateGatewayAPIKeyRequest()
        request.gateway_ids.MergeFrom(self._wrap_gw_id(gateway_id))
        if key_name:
            request.name = key_name
        for right in rights:
            right_enum = tti_contracts.rights_pb2.Right.Value(right)
            request.rights.append(right_enum)

        return await service.CreateAPIKey(request, metadata=self._grpc_meta)

    def assemble_device_pb2(self, **kwargs) -> tti_contracts.end_device_pb2.EndDevice:

        end_device = tti_contracts.end_device_pb2.EndDevice()
        lrwn = tti_contracts.lorawan_pb2

        end_device.ids.MergeFrom(kwargs["ids"])
        end_device.name = kwargs.get("name", "")
        end_device.description = kwargs.get("description", "")
        end_device.network_server_address = kwargs.get("network_server_address", "localhost")
        end_device.application_server_address = kwargs.get("application_server_address", "localhost")
        end_device.join_server_address = kwargs.get("join_server_address", "localhost")
        end_device.supports_class_b = kwargs.get("supports_class_b", False)
        end_device.supports_class_c = kwargs.get("supports_class_c", False)
        end_device.lorawan_version = lrwn.MACVersion.Value(kwargs.get("lorawan_version", "MAC_V1_0_3"))
        end_device.lorawan_phy_version = lrwn.PHYVersion.Value(kwargs.get("lorawan_phy_version", "PHY_V1_0_3_REV_A"))
        end_device.frequency_plan_id = kwargs["frequency_plan_id"]
        if root_keys := kwargs.get("root_keys"):
            end_device.root_keys.MergeFrom(root_keys)
        if session := kwargs.get("session"):
            end_device.session.MergeFrom(session)
        end_device.net_id = kwargs.get("net_id", b"")
        end_device.multicast = kwargs.get("multicast", False)
        end_device.supports_join = kwargs.get("supports_join", False)

        return end_device

    # TODO: All device creation methods are ugly, need refactoring
    async def create_device(self, **kwargs):
        service = tti_contracts.end_device_services_pb2_grpc.EndDeviceRegistryStub(self._channel)

        end_device = self.assemble_device_pb2(**kwargs)
        request = tti_contracts.end_device_pb2.CreateEndDeviceRequest()
        request.end_device.MergeFrom(end_device)
        return await service.Create(request, metadata=self._grpc_meta)

    async def create_ns_device_abp(self, reset_f_cnt: bool = True, **kwargs):
        service = tti_contracts.networkserver_pb2_grpc.NsEndDeviceRegistryStub(self._channel)

        end_device = self.assemble_device_pb2(**kwargs)

        adr_settings = tti_contracts.end_device_pb2.ADRSettings()
        adr_settings.disabled.MergeFrom(tti_contracts.end_device_pb2.ADRSettings.DisabledMode())
        mac_settings = tti_contracts.end_device_pb2.MACSettings()
        mac_settings.adr.MergeFrom(adr_settings)
        end_device.mac_settings.MergeFrom(mac_settings)

        end_device.session.keys.ClearField("app_s_key")
        end_device.ids.ClearField("join_eui")
        end_device.ids.ClearField("dev_addr")
        end_device.ids.ClearField("dev_eui")
        if reset_f_cnt:
            end_device.session.last_f_cnt_up = 1
            end_device.session.last_n_f_cnt_down = 1
            end_device.session.last_conf_f_cnt_down = 1

        request = tti_contracts.end_device_pb2.SetEndDeviceRequest()
        request.end_device.MergeFrom(end_device)
        request.field_mask.MergeFrom(
            FieldMask(
                paths=[
                    "supports_join",
                    "lorawan_version",
                    "ids.device_id",
                    # "ids.dev_eui",
                    "session.keys.nwk_s_enc_key.key",
                    "session.keys.f_nwk_s_int_key.key",
                    "session.keys.s_nwk_s_int_key.key",
                    "session.dev_addr",
                    # "mac_settings.resets_f_cnt",
                    "lorawan_phy_version",
                    "frequency_plan_id",
                    "session.last_f_cnt_up",
                    "session.last_n_f_cnt_down",
                    "session.last_conf_f_cnt_down",
                    "supports_class_b",
                    "supports_class_c",
                    "mac_settings.adr",
                ]
            )
        )
        return await service.Set(request, metadata=self._grpc_meta)

    async def create_ns_device_otaa(self, is_new_device: bool = True, **kwargs):
        service = tti_contracts.networkserver_pb2_grpc.NsEndDeviceRegistryStub(self._channel)

        end_device = self.assemble_device_pb2(**kwargs)
        if not is_new_device:
            end_device.ids.ClearField("dev_eui")
            end_device.ids.ClearField("join_eui")
        end_device.ids.ClearField("dev_addr")
        # end_device.session.Clear()

        request = tti_contracts.end_device_pb2.SetEndDeviceRequest()
        request.end_device.MergeFrom(end_device)
        paths = [
            "supports_join",
            "lorawan_version",
            "supports_class_b",
            "supports_class_c",
            "lorawan_phy_version",
            "frequency_plan_id",
        ]
        if is_new_device:
            paths.extend(["ids.dev_eui", "ids.join_eui"])
        request.field_mask.MergeFrom(FieldMask(paths=paths))
        return await service.Set(request, metadata=self._grpc_meta)

    async def enqueue_downlink(
        self,
        device_ids,
        frm_payload: bytes,
        f_port: int = 1,
        f_cnt: int = 0,
        confirmed: bool = False,
        class_b_c=None,
    ):
        service = tti_contracts.applicationserver_pb2_grpc.AppAsStub(self._channel)

        request = tti_contracts.messages_pb2.DownlinkQueueRequest()
        request.end_device_ids.MergeFrom(self._wrap_dev_id(device_ids))

        downlink = tti_contracts.messages_pb2.ApplicationDownlink()
        downlink.f_port = f_port
        if f_cnt > 0:
            downlink.f_cnt = f_cnt
        downlink.frm_payload = frm_payload
        downlink.confirmed = confirmed
        if class_b_c:
            downlink.class_b_c.MergeFrom(class_b_c)

        request.downlinks.append(downlink)
        # return await service.DownlinkQueuePush(request, metadata=self._grpc_meta)
        return await service.DownlinkQueueReplace(request, metadata=self._grpc_meta)

    async def flush_downlink_queue(self, device_ids):
        service = tti_contracts.applicationserver_pb2_grpc.AppAsStub(self._channel)

        request = tti_contracts.messages_pb2.DownlinkQueueRequest()
        request.end_device_ids.MergeFrom(self._wrap_dev_id(device_ids))
        # return await service.DownlinkQueuePush(request, metadata=self._grpc_meta)
        return await service.DownlinkQueueReplace(request, metadata=self._grpc_meta)

    async def create_js_device(self, **kwargs):
        service = tti_contracts.joinserver_pb2_grpc.JsEndDeviceRegistryStub(self._channel)
        end_device = self.assemble_device_pb2(**kwargs)

        request = tti_contracts.end_device_pb2.SetEndDeviceRequest()
        request.end_device.MergeFrom(end_device)
        request.field_mask.MergeFrom(
            FieldMask(
                paths=[
                    "ids.device_id",
                    "ids.dev_eui",
                    "root_keys",
                ]
            )
        )
        return await service.Set(request, metadata=self._grpc_meta)

    async def create_as_device(self, reset_f_cnt: bool = True, has_dev_addr: bool = True, **kwargs):
        service = tti_contracts.applicationserver_pb2_grpc.AsEndDeviceRegistryStub(self._channel)
        end_device = self.assemble_device_pb2(**kwargs)
        end_device.session.keys.ClearField("nwk_s_enc_key")
        end_device.session.keys.ClearField("f_nwk_s_int_key")
        end_device.session.keys.ClearField("s_nwk_s_int_key")
        end_device.ids.ClearField("join_eui")
        end_device.ids.ClearField("dev_addr")
        # end_device.ids.ClearField("dev_eui")
        if reset_f_cnt:
            # end_device.session.last_f_cnt_up = 0
            end_device.session.last_a_f_cnt_down = 1

        request = tti_contracts.end_device_pb2.SetEndDeviceRequest()
        request.end_device.MergeFrom(end_device)
        paths = [
            "ids.device_id",
            # "ids.dev_eui",
            "session.keys.app_s_key.key",
            # "session.dev_addr",
            "skip_payload_crypto",
            "session.last_a_f_cnt_down",
        ]
        if has_dev_addr:
            paths.append("session.dev_addr")
        request.field_mask.MergeFrom(FieldMask(paths=paths))
        return await service.Set(request, metadata=self._grpc_meta)

    async def delete_device(self, dev_id):
        service = tti_contracts.end_device_services_pb2_grpc.EndDeviceRegistryStub(self._channel)
        return await service.Delete(self._wrap_dev_id(dev_id), metadata=self._grpc_meta)

    async def get_as_device_data(self, dev_id):
        service = tti_contracts.applicationserver_pb2_grpc.AsEndDeviceRegistryStub(self._channel)
        req = tti_contracts.end_device_pb2.GetEndDeviceRequest()

        req.end_device_ids.MergeFrom(self._wrap_dev_id(dev_id))
        req.field_mask.MergeFrom(FieldMask(paths=["session.keys", "session.dev_addr"]))
        return await service.Get(req, metadata=self._grpc_meta)

    # @suppress_rpc_error([grpc.StatusCode.NOT_FOUND, grpc.StatusCode.UNAUTHENTICATED])
    # async def get_device(self, dev_eui: str):
    #     client = api.DeviceServiceStub(self._channel)

    #     req = api.GetDeviceRequest()
    #     req.dev_eui = dev_eui

    #     res = await client.Get(req, metadata=self._auth_token)
    #     return res.device

    # async def create_device_keys(self, dev_eui: str, nwk_key: str, app_key: Optional[str] = None) -> None:
    #     client = api.DeviceServiceStub(self._channel)

    #     req = api.CreateDeviceKeysRequest()
    #     req.device_keys.dev_eui = dev_eui
    #     req.device_keys.nwk_key = nwk_key
    #     req.device_keys.app_key = app_key
    #     # req.device_keys.gen_app_key = ...

    #     await client.CreateKeys(req, metadata=self._auth_token)

    # async def activate_device(self, dev_eui: str, **kwargs) -> None:
    #     import secrets

    #     client = api.DeviceServiceStub(self._channel)

    #     req = api.ActivateDeviceRequest()
    #     device_activation = req.device_activation

    #     device_activation.dev_eui = dev_eui
    #     device_activation.dev_addr = kwargs.get("dev_addr", secrets.token_hex(4))
    #     device_activation.app_s_key = kwargs.get("app_s_key", secrets.token_hex(16))
    #     device_activation.nwk_s_enc_key = kwargs.get("nwk_s_enc_key", secrets.token_hex(16))

    #     device_activation.s_nwk_s_int_key = kwargs.get("s_nwk_s_int_key", device_activation.nwk_s_enc_key)
    #     device_activation.f_nwk_s_int_key = kwargs.get("f_nwk_s_int_key", device_activation.nwk_s_enc_key)

    #     device_activation.f_cnt_up = kwargs.get("f_cnt_up", 0)
    #     device_activation.n_f_cnt_down = kwargs.get("n_f_cnt_down", 0)
    #     device_activation.a_f_cnt_down = kwargs.get("a_f_cnt_down", 0)

    #     await client.Activate(req, metadata=self._auth_token)

    # async def delete_device_profile(self, device_profile_id: str) -> None:
    #     client = api.DeviceProfileServiceStub(self._channel)

    #     req = api.DeleteDeviceProfileRequest()
    #     req.id = device_profile_id

    #     await client.Delete(req, metadata=self._auth_token)

    # async def create_device_profile(self, **kwargs):
    #     client = api.DeviceProfileServiceStub(self._channel)

    #     req = api.CreateDeviceProfileRequest()
    #     device_profile = req.device_profile
    #     device_profile.name = kwargs["name"]
    #     device_profile.tenant_id = kwargs["tenant_id"]
    #     device_profile.description = kwargs.get("description", "")
    #     device_profile.region = common_pb2.Region.Value(kwargs.get("region", "EU868"))
    #     device_profile.mac_version = kwargs.get("mac_version", common_pb2.MacVersion.LORAWAN_1_0_3)
    #     device_profile.reg_params_revision = kwargs.get("reg_params_revision", common_pb2.RegParamsRevision.RP002_1_0_2)
    #     device_profile.adr_algorithm_id = kwargs.get("adr_algorithm_id", "default")
    #     device_profile.payload_codec_runtime = kwargs.get("payload_codec_runtime", 0)
    #     device_profile.payload_codec_script = kwargs.get("payload_codec_script", b"")
    #     device_profile.flush_queue_on_activate = kwargs.get("flush_queue_on_activate", False)
    #     device_profile.uplink_interval = kwargs.get("uplink_interval", 1000 * 60 * 5)
    #     device_profile.device_status_req_interval = kwargs.get("device_status_req_interval", 1)
    #     device_profile.supports_otaa = kwargs.get("supports_otaa", False)
    #     device_profile.supports_class_b = kwargs.get("supports_class_b", False)
    #     device_profile.supports_class_c = kwargs.get("supports_class_c", False)
    #     device_profile.class_b_timeout = kwargs.get("class_b_timeout", 0)
    #     # device_profile.class_b_ping_slot_period = kwargs.get("class_b_ping_slot_period", 0)
    #     device_profile.class_b_ping_slot_dr = kwargs.get("class_b_ping_slot_dr", 0)
    #     device_profile.class_b_ping_slot_freq = kwargs.get("class_b_ping_slot_freq", 0)
    #     device_profile.class_c_timeout = kwargs.get("class_c_timeout", 0)
    #     device_profile.abp_rx1_delay = kwargs.get("abp_rx1_delay", 1)
    #     device_profile.abp_rx1_dr_offset = kwargs.get("abp_rx1_dr_offset", 0)
    #     device_profile.abp_rx2_dr = kwargs.get("abp_rx2_dr", 0)
    #     device_profile.abp_rx2_freq = kwargs.get("abp_rx2_freq", 0)
    #     device_profile.tags.clear()
    #     for k, v in kwargs.get("tags", {}).items():
    #         device_profile.tags[k] = v

    #     res = await client.Create(req, metadata=self._auth_token)
    #     return res.id

    # async def create_device(self, **kwargs) -> str:
    #     client = api.DeviceServiceStub(self._channel)

    #     req = api.CreateDeviceRequest()
    #     req.device.dev_eui = kwargs["dev_eui"]
    #     req.device.name = kwargs["name"]
    #     req.device.application_id = kwargs["application_id"]
    #     req.device.description = kwargs.get("description", "")
    #     req.device.device_profile_id = kwargs["device_profile_id"]
    #     req.device.is_disabled = kwargs.get("is_disabled", False)
    #     req.device.skip_fcnt_check = kwargs.get("skip_fcnt_check", True)
    #     req.device.tags.update(kwargs.get("tags", {}))

    #     await client.Create(req, metadata=self._auth_token)
    #     return kwargs["dev_eui"]

    # async def delete_device(self, dev_eui):
    #     client = api.DeviceServiceStub(self._channel)

    #     req = api.DeleteDeviceRequest()
    #     req.dev_eui = dev_eui

    #     return await client.Delete(req, metadata=self._auth_token)

    # async def create_application(self, **kwargs) -> int:
    #     client = api.ApplicationServiceStub(self._channel)

    #     req = api.CreateApplicationRequest()
    #     application = req.application
    #     application.name = kwargs["name"]
    #     application.description = kwargs.get("description", "")
    #     application.tenant_id = kwargs["tenant_id"]

    #     response = await client.Create(req, metadata=self._auth_token)
    #     return response.id

    # @suppress_rpc_error([grpc.StatusCode.NOT_FOUND, grpc.StatusCode.UNAUTHENTICATED])
    # async def get_application(self, application_id: int):
    #     client = api.ApplicationServiceStub(self._channel)

    #     req = api.GetApplicationRequest()
    #     req.id = application_id

    #     res = await client.Get(req, metadata=self._auth_token)
    #     return res.application

    # async def delete_application(self, application_id: int):
    #     client = api.ApplicationServiceStub(self._channel)

    #     req = api.DeleteApplicationRequest()
    #     req.id = application_id

    #     return await client.Delete(req, metadata=self._auth_token)

    # async def delete_gateway(self, gateway_id):
    #     client = api.GatewayServiceStub(self._channel)

    #     req = api.DeleteGatewayRequest()
    #     req.gateway_id = gateway_id

    #     return await client.Delete(req, metadata=self._auth_token)

    # async def enqueue_downlink(self, dev_eui, data: bytes, confirmed: bool = False, f_port: int = 2):
    #     client = api.DeviceServiceStub(self._channel)

    #     req = api.EnqueueDeviceQueueItemRequest()
    #     req.queue_item.confirmed = confirmed
    #     req.queue_item.data = data
    #     req.queue_item.dev_eui = dev_eui
    #     req.queue_item.f_port = f_port

    #     return await client.Enqueue(req, metadata=self._auth_token)

    # async def create_multicast_group(self, **kwargs) -> str:
    #     client = api.MulticastGroupServiceStub(self._channel)

    #     mc = api.MulticastGroup()
    #     mc.name = kwargs["name"]
    #     mc.application_id = kwargs["application_id"]
    #     mc.region = common_pb2.Region.Value(kwargs["region"])
    #     mc.mc_addr = kwargs["mc_addr"]
    #     mc.mc_nwk_s_key = kwargs["mc_nwk_s_key"]
    #     mc.mc_app_s_key = kwargs["mc_app_s_key"]
    #     mc.f_cnt = kwargs.get("f_cnt", 0)
    #     mc.group_type = api.MulticastGroupType.Value(kwargs["group_type"])
    #     mc.dr = kwargs.get("dr", 0)
    #     mc.frequency = kwargs["frequency"]
    #     mc.class_b_ping_slot_period = kwargs.get("class_b_ping_slot_period", 0)

    #     req = api.CreateMulticastGroupRequest()
    #     req.multicast_group.MergeFrom(mc)
    #     response = await client.Create(req, metadata=self._auth_token)
    #     return response.id

    # async def add_device_to_multicast_group(self, group_id: str, dev_eui: str):
    #     client = api.MulticastGroupServiceStub(self._channel)

    #     req = api.AddDeviceToMulticastGroupRequest()
    #     req.multicast_group_id = group_id
    #     req.dev_eui = dev_eui

    #     return await client.AddDevice(req, metadata=self._auth_token)

    # async def delete_multicast_group(self, group_id: str):
    #     client = api.MulticastGroupServiceStub(self._channel)
    #     req = api.DeleteMulticastGroupRequest()
    #     req.id = group_id

    #     return await client.Delete(req, metadata=self._auth_token)

    # async def enqueue_multicast_downlink(self, group_id: str, f_port: int, data: bytes, f_cnt: Optional[int] = None):
    #     client = api.MulticastGroupServiceStub(self._channel)

    #     multicast = api.MulticastGroupQueueItem()
    #     multicast.multicast_group_id = group_id
    #     if f_cnt is not None:
    #         multicast.f_cnt = f_cnt
    #     multicast.f_port = f_port
    #     multicast.data = data

    #     req = api.EnqueueMulticastGroupQueueItemRequest(queue_item=multicast)

    #     return await client.Enqueue(req, metadata=self._auth_token)
