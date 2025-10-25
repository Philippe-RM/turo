FROM rayproject/ray:2.51.0.b6b1fa-cpu

USER root
WORKDIR /app

COPY entrypoint.sh .

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]