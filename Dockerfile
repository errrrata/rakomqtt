ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /usr/src/app

RUN \
    apk add --no-cache \
    python3 \
    py3-pip \
    gcc \
    musl-dev \
    linux-headers \
    curl

COPY requirements.txt /usr/src/app/
COPY run.sh /usr/src/app/
COPY rako_mqtt_bridge /usr/src/app/rako_mqtt_bridge/

RUN \
    python3 -m venv /usr/src/app && \
    . /usr/src/app/bin/activate && \
    pip install --no-cache-dir -r /usr/src/app/requirements.txt

#RUN pip3 install --no-cache-dir -r requirements.txt


# Copy data for add-on
RUN chmod a+x /usr/src/app/run.sh

CMD [ "/usr/src/app/run.sh" ]