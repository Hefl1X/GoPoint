# Инструмент для вырезания города из выгрузки OpenStreetMap (osmium).
FROM debian:12.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends osmium-tool \
 && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["osmium"]
