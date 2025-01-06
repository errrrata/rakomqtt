FROM python:3.7

ADD requirements.txt /deploy/
ADD start.sh /deploy/
WORKDIR /deploy

RUN pip install -r requirements.txt
RUN chmod +x /deploy/start.sh

ADD ./rakomqtt /deploy/rakomqtt/

ENV RAKO_BRIDGE_HOST=""

CMD ["./start.sh"]
