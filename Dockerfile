# GluChron poller: phpexperts/dockerize distroless PHP CLI plus GnuPG.
# The distroless image has no CA bundle. libcurl's default is
# /etc/ssl/certs/ca-certificates.crt; without that file every LibreLinkUp
# call fails with cURL error 77 before Abbott answers.
# PHP is not built here. Local CLI bootstrap (no host PHP):
#   bash <(curl -s 'https://raw.githubusercontent.com/PHPExpertsInc/dockerize/v15.x/dockerize.sh')
ARG PHP_VERSION=8.4

FROM ubuntu:24.04 AS gpg
COPY docker/grab-gpg.sh /grab-gpg.sh
RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && sh /grab-gpg.sh \
    && mkdir -p /out/etc/ssl/certs \
    && cp -L /etc/ssl/certs/ca-certificates.crt /out/etc/ssl/certs/ca-certificates.crt

FROM phpexperts/php:${PHP_VERSION}
COPY --from=gpg /out/ /
COPY docker/entrypoint.sh /usr/bin/gluchron-entrypoint
WORKDIR /workdir
ENV APP_ENV=production
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD php -r 'exit(@fsockopen("127.0.0.1", (int) (getenv("PORT") ?: 8765)) ? 0 : 1);'
ENTRYPOINT ["/usr/bin/gluchron-entrypoint"]
