from lib.environs import Env

env = Env()
env.read_env()

# TTI gRPS access variables
TTI_GRPC_API_HOST = env("TTI_GRPC_API_HOST", "localhost")
TTI_GRPC_API_PORT = env.int("TTI_GRPC_API_PORT", 1884)
TTI_GRPC_API_SECURE = env.bool("TTI_GRPC_API_SECURE", False)
TTI_GRPC_API_CERT_PATH = env("TTI_GRPC_API_CERT_PATH", None)
TTI_GRPC_API_TOKEN = env("TTI_GRPC_API_TOKEN")

# TTI MQTT access variables
TTI_GW_MQTT_HOST = env("TTI_GW_MQTT_HOST", "localhost")
TTI_GW_MQTT_PORT = env.int("TTI_GW_MQTT_PORT", 1882)
TTI_GW_MQTT_SECURE = env.bool("TTI_GW_MQTT_SECURE", False)
TTI_GW_MQTT_CERT_PATH = env("TTI_GW_MQTT_CERT_PATH", None)
TTI_GW_MQTT_TOKEN = env("TTI_GW_MQTT_TOKEN")

TTI_GATEWAY_ID = env("TTI_GATEWAY_ID", "eui-000000000000c0de")
TTI_TENANT_ID = env("TTI_TENANT_ID", None)

# Ran access variables
RAN_API_URL = env("RAN_API_URL")
RAN_API_TOKEN = env("RAN_API_TOKEN")

# Bridge configuration variables
BRIDGE_DEVICE_MATCH_TAGS = env("BRIDGE_DEVICE_MATCH_TAGS", "everynet=true")
BRIDGE_DEVICES_REFRESH_PERIOD = env.int("BRIDGE_DEVICES_REFRESH_PERIOD", 300)

# Logging conf
BRIDGE_LOG_LEVEL = env("BRIDGE_LOG_LEVEL", "info")
BRIDGE_LOG_COLORS = env.bool("BRIDGE_LOG_COLORS", True)
BRIDGE_LOG_JSON = env.bool("BRIDGE_LOG_JSON", False)

# Health-check conf
BRIDGE_HEALTHCHECK_SERVER_HOST = env("BRIDGE_HEALTHCHECK_SERVER_HOST", "0.0.0.0")
BRIDGE_HEALTHCHECK_SERVER_PORT = env.int("BRIDGE_HEALTHCHECK_SERVER_PORT", 9090)


# utility
def get_tags(value: str) -> dict:
    if not value:
        return {}

    parts = value.split("=", 1)
    if len(parts) > 1:
        return {parts[0]: parts[1]}

    return {parts[0]: ""}
