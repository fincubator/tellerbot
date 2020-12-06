#!/bin/sh
mongo -- "${MONGO_INITDB_DATABASE-$DATABASE_NAME}" <<EOF
db.createUser(
    {
        user: "${MONGO_INITDB_ROOT_USERNAME:-$DATABASE_USERNAME}",
        pwd: "$(printf %s "${MONGO_INITDB_ROOT_PASSWORD:-$(cat ${DATABASE_PASSWORD_FILENAME})}")",
        roles: ["readWrite"]
    }
);
EOF
