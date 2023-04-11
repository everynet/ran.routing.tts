FROM python:3.10.9-slim-buster as builder

ARG ENVIRONMENT
ENV ENVIRONMENT=${ENVIRONMENT:-production}

# Install dependencies
RUN apt-get update && apt-get install --no-install-recommends --yes \
    apt-transport-https \
    ca-certificates \
    build-essential \
    g++ \
    git \
    libssl-dev \
    bash \
    dumb-init \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*
RUN pip install -U pip poetry==1.3.2
RUN poetry config virtualenvs.create false

FROM builder as contracts_builder

# This builder will collect and build sdk for TTI
ADD contracts /contracts
WORKDIR /contracts
RUN poetry install --no-dev --no-root \
    && if [ "$ENVIRONMENT" = "development" ]; then poetry install; fi
RUN python sdk_builder.py build
RUN python sdk_builder.py clean src

FROM builder as dependency_builder

# This copy required to create "tti_contracts-x.x.x.dist-info" in /usr/local/lib/python3.10/site-packages/
COPY --from=contracts_builder /contracts /contracts
COPY poetry.lock /
COPY pyproject.toml /
RUN poetry install --no-dev --no-root \
    && if [ "$ENVIRONMENT" = "development" ]; then poetry install; fi

FROM python:3.10.9-slim-buster

# This copy required to create real sources in /contracts folder
COPY --from=contracts_builder /contracts /contracts
COPY --from=dependency_builder /usr/local /usr/local
ADD src /app
WORKDIR /app

ENV PATH="/app:${PATH}"
CMD ["python", "main.py"]
