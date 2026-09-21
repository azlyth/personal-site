# Zola is not installed natively on the Pi; every site build runs in here.
FROM alpine:3.20
RUN apk add --no-cache zola
WORKDIR /project
