FROM python:3.8

RUN pip install pipenv
COPY Pipfile* /tmp/
RUN cd /tmp && pipenv lock --requirements > /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

RUN mkdir /opt/frisbeer-backend
RUN mkdir /var/static

COPY djangofiles/ /opt/frisbeer-backend/
COPY create_ranks.py /opt/frisbeer-backend/create_ranks.py
COPY docker/start.sh /opt/frisbeer-backend/start.sh

RUN chmod +x /opt/frisbeer-backend/start.sh

COPY docker/settings.py /opt/frisbeer-backend/server/settings.py

WORKDIR /opt/frisbeer-backend/

ENTRYPOINT ["./start.sh"]
