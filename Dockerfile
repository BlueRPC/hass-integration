FROM homeassistant/home-assistant:2023.8

RUN sed "s/after_dependencies\": \[/after_dependencies\"\: \[\"bluerpc\", /" /usr/src/homeassistant/homeassistant/components/bluetooth_adapters/manifest.json && \
    pip install bluerpc-client==0.3.2

