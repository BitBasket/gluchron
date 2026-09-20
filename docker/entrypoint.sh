#!/bin/sh
set -eu

cd /workdir

mkdir -p /workdir/data/keys /workdir/public /workdir/public/b

if [ ! -r "${PGP_PUBLIC_KEY_PATH:-data/keys/public.asc}" ] || [ ! -r "${PGP_PRIVATE_KEY_PATH:-data/keys/private.asc}" ]; then
    echo "PGP keys are missing; generating them with php bin/init-pgp.php"
    php bin/init-pgp.php
fi

exec php bin/serve.php "$@"
