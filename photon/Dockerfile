# Свой сервер поиска адресов Photon только по Новосибирску.
# База собирается скриптом scripts/build-photon-db.sh из выгрузки GraphHopper.
FROM eclipse-temurin:21.0.12.1_1-jre

# zstd: распаковка выгрузки, python3: вырезание города (только стандартная библиотека).
RUN apt-get update \
 && apt-get install -y --no-install-recommends zstd python3-minimal curl \
 && rm -rf /var/lib/apt/lists/*

ARG PHOTON_VERSION=1.3.0
ARG PHOTON_SHA256=a89707c0045e4807b2a1180e132e68e108d998709f48b6c94b98a6e281f571a5
RUN curl -fsSL -o /opt/photon.jar \
      "https://github.com/komoot/photon/releases/download/${PHOTON_VERSION}/photon-${PHOTON_VERSION}.jar" \
 && echo "${PHOTON_SHA256}  /opt/photon.jar" | sha256sum -c -

COPY extract_city.py import.sh serve.sh /opt/
RUN chmod +x /opt/import.sh /opt/serve.sh \
 && useradd --system --home /data photon && mkdir -p /data && chown photon /data
USER photon
WORKDIR /data
EXPOSE 2322
CMD ["/opt/serve.sh"]
