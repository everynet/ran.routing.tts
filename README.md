
# Everynet RAN to  bridge

It is an early stage beta product. Please refer to the known limitations section.

## Introduction

Everynet operates a Neutral-Host Cloud RAN, which is agnostic to the LoRaWAN Network Server. Everynet's main product is carrier-grade coverage that can be connected to any LNS available on the market and ChirpStack in particular.

Everynet coverage is available via Everynet RAN Routing API that let customers control message routing table (subscribe to devices). It also allows to send and receive LoRaWAN messages.

This integration is designed to simplify the connection between the Everynet RAN Routing API and TTI installation.

## Functionality

With this software, you can connect [The Things Stack for LoRaWAN]([https://www.thethingsindustries.com/docs/]) application to Everynet RAN coverage.

Before we start it is important to mention that Everynet RAN main functionality is LoRaWAN traffic routing, while TTI is doing the rest of the job: device and key management, payload parsing and so on...

**Everynet RAN does not store any device-related cryptographic keys and is not capable of decrypting customer traffic.**


## Configuration

Before using this software you should configure the following parameters. Make sure that you correctly set all the required parameters.

Parameters are read from environment variables and/or **settings.cfg** and **.env** files.

For docker-compose deployment you can use config template from [`.env-dist-docker`](./.env-dist-docker). Copy this file contents into `.env` before following docker-compose deployment guide below.

```bash
cp .env-dist-docker .env
```

Template with all config variables with their default can be found at [`.env-dist`](./.env-dist).


| Variable                       | Required | Default value | Description                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------ | -------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| TTI_GRPC_API_HOST              | Yes      | localhost     | TTI management API gRPC host. Refer [Addresses](https://www.thethingsindustries.com/docs/getting-started/ttn/addresses/) section of TTI docs to select correct value.                                                                                                                                                                                                                |
| TTI_GRPC_API_PORT              | Yes      | 1884          | TTI management API gRPC port. Refer [Networking](https://www.thethingsindustries.com/docs/reference/networking/) section of TTI docs to select correct value.                                                                                                                                                                                                                        |
| TTI_GRPC_API_TOKEN             | Yes      |               | TTI management API access key. Support only admin user tokens with full rights. Read more at [Authentication](https://www.thethingsindustries.com/docs/reference/api/authentication/) section of TTI docs.                                                                                                                                                                           |
| TTI_GRPC_API_SECURE            |          | False         | TTI management API connection secure on not. Refer [Networking](https://www.thethingsindustries.com/docs/reference/networking/) section of TTI docs to select correct value.                                                                                                                                                                                                         |
| TTI_GRPC_API_CERT_PATH         |          |               | If you are using custom certificates for gRPC secure connection, you must specify certificate file path here.                                                                                                                                                                                                                                                                        |
| TTI_GW_MQTT_HOST               | Yes      | localhost     | TTI [gateway server MQTT](https://www.thethingsindustries.com/docs/reference/api/gateway_server_mqtt/#mqtt-introduction) host. Refer [Addresses](https://www.thethingsindustries.com/docs/getting-started/ttn/addresses/) section of TTI docs to select correct value.                                                                                                               |
| TTI_GW_MQTT_PORT               | Yes      | 1882          | TTI [gateway server MQTT](https://www.thethingsindustries.com/docs/reference/api/gateway_server_mqtt/#mqtt-introduction) port. Refer [Networking](https://www.thethingsindustries.com/docs/reference/networking/) section of TTI docs to select correct value.                                                                                                                       |
| TTI_GW_MQTT_TOKEN              | Yes      |               | TTI [gateway server MQTT](https://www.thethingsindustries.com/docs/reference/api/gateway_server_mqtt/#mqtt-introduction) access key. Support only gateway tokens with full rights. You can create this key by following instructions from [Adding Gateways](https://www.thethingsindustries.com/docs/gateways/concepts/adding-gateways/#create-gateway-api-key) section of TTI docs. |
| TTI_GW_MQTT_SECURE             |          | False         | TTI [gateway server MQTT](https://www.thethingsindustries.com/docs/reference/api/gateway_server_mqtt/#mqtt-introduction) connection secure on not. Refer [Networking](https://www.thethingsindustries.com/docs/reference/networking/) section of TTI docs to select correct value.                                                                                                   |
| TTI_GW_MQTT_CERT_PATH          |          |               | If you are using custom certificates for MQTT secure connection, you must specify certificate file path here.                                                                                                                                                                                                                                                                        |
| TTI_GATEWAY_ID                 | Yes      |               | Identifier of virtual gateway from which messages will be arriving to the TTI.                                                                                                                                                                                                                                                                                                       |
| TTI_TENANT_ID                  |          |               | On multi-tenant environments such as Cloud, MQTT endpoints must include the tenant id, e.g `$TTI_GATEWAY_ID@$TTI_TENANT_ID`. On single tenant environments such as Open Source, the tenant id can be not specified.                                                                                                                                                                  |
| RAN_API_URL                    | Yes      |               | RAN Routing API endpoint URL.                                                                                                                                                                                                                                                                                                                                                        |
| RAN_API_TOKEN                  | Yes      |               | RAN Routing API access token.                                                                                                                                                                                                                                                                                                                                                        |
| BRIDGE_DEVICE_MATCH_TAGS       |          | everynet=true | Mark devices with the "everynet=true" attribute to connect them to Everynet coverage. Here you can change name and value of this attribute. <br>***IMPORTANT:*** If set to an empty string, all devices will be synced with RAN.                                                                                                                                                     |
| BRIDGE_DEVICES_REFRESH_PERIOD  | Yes      | 300           | Period in seconds to fetch device list from the TTI and sync it with Everynet RAN Routing.                                                                                                                                                                                                                                                                                           |
| BRIDGE_LOG_LEVEL               |          | info          | Bridge logging level. Allowed values: info, warning, error, debug.                                                                                                                                                                                                                                                                                                                   |
| BRIDGE_LOG_COLORS              |          | True          | Enable/disable ascii color-codes for textual log output. This option ignored, if `BRIDGE_LOG_JSON=True`                                                                                                                                                                                                                                                                              |
| BRIDGE_LOG_JSON                |          | False         | Enable/disable json instead of text logs                                                                                                                                                                                                                                                                                                                                             |
| BRIDGE_HEALTHCHECK_SERVER_HOST |          | 0.0.0.0       | Internal healthcheck http server bind host. Health probes will be available at `http://[host]:[port]/health/live` and `http://[host]:[port]/health/ready`                                                                                                                                                                                                                            |
| BRIDGE_HEALTHCHECK_SERVER_PORT |          | 9090          | Internal healthcheck http server bind port.                                                                                                                                                                                                                                                                                                                                          |


---


## Deploying TTI and Ran-Bridge with docker-compose

For now it is only possible to deploy this bridge using docker and docker-compose.
If you don't have any installation of ChirpStack first you need to deploy it. For reference you can use docker-compose files from this repository.

### 1. Build tti-ran-bridge docker image

```
docker-compose -f docker-compose.tti.yml -f docker-compose.bridge.yml build
```

### 2. Start TTI lorawan stack and it's dependencies

```
docker-compose -f docker-compose.tti.yml up -d
```

All TTI data volumes will be mounted into ".docker-env" folder of current directory. You can change this path by setting `$DEV_DATA_DIR` env variable.

If you need to purge all TTI data, execute:

```bash
sudo rm -rf ./.docker-env
```

### 3. Initial TTI configuration

You can read more about configuring TTI on website: https://www.thethingsindustries.com/docs/getting-started/installation/running-the-stack/

Perform migrations:

```bash
docker-compose -f docker-compose.tti.yml run --rm stack is-db migrate
```

Create admin user. This will ask you to enter admin password.

```bash
docker-compose -f docker-compose.tti.yml run --rm stack is-db create-admin-user \
  --id admin \
  --email admin@admin.com
```

<details>
  <summary>One-line command</summary>

```bash
docker-compose -f docker-compose.tti.yml run --rm stack is-db create-admin-user --id admin --email admin@admin.com
```

</details>


Create required OAuth secrets for created user:

```bash
docker-compose -f docker-compose.tti.yml run --rm stack is-db create-oauth-client \
  --id cli \
  --name "Command Line Interface" \
  --owner admin \
  --no-secret \
  --redirect-uri "local-callback" \
  --redirect-uri "code"
```

<details>
  <summary>One-line command</summary>

```bash
docker-compose -f docker-compose.tti.yml run --rm stack is-db create-oauth-client --id cli --name "Command Line Interface" --owner admin --no-secret --redirect-uri "local-callback" --redirect-uri "code"
```

</details>


Adding OAuth auth flow for created user. Here we are exporting some required variables.

This export commands requires `GNU grep >=3.8` and `GNU findutils xargs >=4.9.0`. If you don't have this utils, you can set those variables in your shell manually, according to ".env-tti-console" file contents.

```bash
export $(grep -v '^#' .env-tti-console | xargs) && \ # Exporting variables
docker-compose -f docker-compose.tti.yml run --rm stack is-db create-oauth-client \
  --id ${ID} \
  --name "${NAME}" \
  --owner admin \
  --secret "${CLIENT_SECRET}" \
  --redirect-uri "${REDIRECT_URI}" \
  --redirect-uri "${REDIRECT_PATH}" \
  --logout-redirect-uri "${LOGOUT_REDIRECT_URI}" \
  --logout-redirect-uri "${LOGOUT_REDIRECT_PATH}" && \
unset $(grep -oP '^[^#].*(?=\=.*)' .env-tti-console | xargs) # Removing variables from environment
```

<details>
  <summary>One-line command</summary>

```bash
export $(grep -v '^#' .env-tti-console | xargs) && docker-compose -f docker-compose.tti.yml run --rm stack is-db create-oauth-client   --id ${ID} --name "${NAME}" --owner admin --secret "${CLIENT_SECRET}" --redirect-uri "${REDIRECT_URI}" --redirect-uri "${REDIRECT_PATH}" --logout-redirect-uri "${LOGOUT_REDIRECT_URI}" --logout-redirect-uri "${LOGOUT_REDIRECT_PATH}" && unset $(grep -oP '^[^#].*(?=\=.*)' .env-tti-console | xargs)

```

</details>

After this step you can access TTI stack UI at `http://localhost:1885/` with login "admin" and password, set earlier.


### 4. Configuring TTI for Ran-Bridge

#### 4.1. Creating Ran-Bridge config

Create ".env" file with settings for ran-bridge. You can use `.env-dist-docker` with pre-filled variable names.

```bash
cp .env-dist-docker .env
```

#### 4.2. Creating access token

```bash
docker-compose -f docker-compose.tti.yml run --rm stack is-db create-user-api-key --user-id admin
```

After executing this command, copy token, written after "API key value:" into .env file as `TTI_GRPC_API_TOKEN` variable


#### 4.3. Login into TTI cli app

Use token, obtained on previous step as `TTI_GRPC_API_TOKEN` variable value. Ensure, tti stack is [running](#2-start-tti-lorawan-stack-and-its-dependencies), before executing those commands.

```bash
export TTI_GRPC_API_TOKEN="NNSXS.RXYVZS<...>SMOHCN2MZXTK6PMGXQ"
docker-compose -f docker-compose.tti.yml exec stack ttn-lw-cli login --api-key="${TTI_GRPC_API_TOKEN}"
```

#### 4.4. Creating gateway

Check frequency plans and choose one, copy it's "id" value, it is required for next step.

```bash
docker-compose -f docker-compose.tti.yml exec stack ttn-lw-cli gateways list-frequency-plans
```

To create gateway, execute:

```bash
docker-compose -f docker-compose.tti.yml exec stack ttn-lw-cli gateways create --user-id admin --frequency-plan-id EU_863_870 --gateway-eui 000000000000c0de --status-public=0 --location-public=0 --auto-update=0 ran-bridge
```

In this example, we are creating gateway "ran-bridge" with frequency plan `EU_863_870` and gateway-eui `000000000000c0de`.


#### 4.5. Creating gateway access token

```bash
docker-compose -f docker-compose.tti.yml exec stack ttn-lw-cli gateways api-keys create --name ran-bridge-key --right-gateway-all ran-bridge
```

After executing this command, copy token, written after "API key value: " into into .env as `TTI_GW_MQTT_TOKEN` variable


### 5. Configuring RAN access

Edit .env file and set your RAN token in `RAN_API_TOKEN` variable and api URL in `RAN_API_URL` variable.

You can obtain this values from RAN cloud UI - https://cloud.everynet.io/


### 6. Starting Ran-Bridge

On this step, your `.env` file must contain several required values, example:

```env
# GRPC API access settings
TTI_GRPC_API_TOKEN="NNSXS.DKF7BJ5X<...>DXN3OCSGOZTPKWX2A4Q"

# MQTT access settings
TTI_GW_MQTT_TOKEN="NNSXS.INICRCIKTO<...>KVMNWJSZHK6VCIIGYA"
TTI_GATEWAY_ID="ran-bridge"

# RAN access settings
RAN_API_URL="https://dev.cloud.dev.everynet.io/api/v1"
RAN_API_TOKEN="eyJhbGciOiJFUzI<...>645e7UW6N38ew"

# Bridge settings
BRIDGE_LOG_LEVEL="info"
BRIDGE_DEVICES_REFRESH_PERIOD="300"
```

Now, you can run configured RAN-bridge.

```
docker-compose -f docker-compose.tti.yml -f docker-compose.bridge.yml up -d
```

TTI stack with tti-ran-bridge will be available at `http://<YOUR DOMAIN>:1885`


---

## Deploying Ran-Bridge with docker

Ran-Bridge has [pre-builded docker images](https://hub.docker.com/r/everynethub/ran.routing.tti).
You must have an existing TTI installation or you can install TTI using docker-compose from section above.

To run Ran-Bridge you must specify the required parameters listed above.
Example command below shows the main required parameters and their typical values.

Example for self-hosted (open source) TTI environment:

```bash
docker run -d --name=ran-bridge --restart=always \
    -e TTI_GRPC_API_HOST="localhost" \
    -e TTI_GRPC_API_PORT="1884" \
    -e TTI_GRPC_API_SECURE="False" \
    -e TTI_GRPC_API_TOKEN="<...>" \
    -e TTI_GW_MQTT_HOST="myhost.com" \
    -e TTI_GW_MQTT_PORT="1882" \
    -e TTI_GW_MQTT_SECURE="False" \
    -e TTI_GW_MQTT_TOKEN="<...>" \
    -e TTI_GATEWAY_ID="eui-000000000000c0de" \
    -e RAN_API_URL="https://eu.cloud.everynet.io/api/v1" \
    -e RAN_API_TOKEN="<...>" \
    everynethub/ran.routing.tti
```

Example for cloud TTI environment:

```bash
docker run -d --name=ran-bridge --restart=always \
    -e TTI_GRPC_API_HOST="mytenant.eu1.cloud.thethings.industries" \
    -e TTI_GRPC_API_PORT="8884" \
    -e TTI_GRPC_API_SECURE="True" \
    -e TTI_GRPC_API_TOKEN="<...>" \
    -e TTI_GW_MQTT_HOST="mytenant.eu1.cloud.thethings.industries" \
    -e TTI_GW_MQTT_PORT="8882" \
    -e TTI_GW_MQTT_SECURE="True" \
    -e TTI_GW_MQTT_TOKEN="<...>" \
    -e TTI_GATEWAY_ID="eui-000000000000c0de" \
    -e TTI_TENANT_ID="mytenant" \
    -e RAN_API_URL="https://eu.cloud.everynet.io/api/v1" \
    -e RAN_API_TOKEN="<...>" \
    everynethub/ran.routing.tti
```


---


## Manual tti GRPC SDK building

This instructions can be useful for developers. This steps are not required for service deployment.

Install dependencies:

```bash
cd contracts
pyenv virtualenv 3.10.9 tti-contracts && pyenv local tti-contracts # you can skip this step, if you are not using pyenv
python -m venv ./.venv && source ./.venv/bin/activate  # you can skip this step, if you are not using virtualenv
pip install poetry
poetry install --no-root
```

Other dependency is `git` binary, available in PATH.

Build SDK:

```bash
python sdk_builder.py build
```

After this build, sdk will be available in "./contracts/tti_contracts" folder.

To remove built sdk you can run

```bash
python sdk_builder.py clean dst
```

To remove cloned tti lorawan-stack repo you can run

```bash
python sdk_builder.py clean src
```


---


## Known limitations

These are the known limitations that are going to be fixed in the next versions of this software:

- Class B downlinks may have scheduling issues.
- Multicast groups are not supported.
- Neither FSK, nor LR-FHSS modulations are supported.
- Requires TTI admin user API access key with full rights to operate, not supports Application/Organization API keys.
- Requires TTI gateway MQTT access key with full rights to operate.
