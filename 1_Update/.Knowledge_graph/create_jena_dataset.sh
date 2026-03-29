#!/bin/bash

# Configuration
FUSEKI_URL="http://localhost:3030"
DATASET_NAME="tender"
ADMIN_USER="admin"
ADMIN_PASS="admin"

echo "Creating Jena Fuseki dataset: ${DATASET_NAME}..."

# Create dataset using Fuseki Administration API
# dbType=tdb2 is recommended for persistent storage
RESPONSE=$(curl -s -u "${ADMIN_USER}:${ADMIN_PASS}" \
     -X POST "${FUSEKI_URL}/\$/datasets" \
     --data "dbName=${DATASET_NAME}&dbType=tdb2")

if [[ $RESPONSE == *"Duplicate name"* ]]; then
    echo "Dataset '${DATASET_NAME}' already exists."
elif [[ $RESPONSE == *"${DATASET_NAME}"* ]]; then
    echo "✓ Successfully created dataset '${DATASET_NAME}'."
else
    echo "✗ Failed to create dataset. Response:"
    echo "$RESPONSE"
    exit 1
fi

# Verify
echo "Verifying available datasets..."
curl -s -u "${ADMIN_USER}:${ADMIN_PASS}" "${FUSEKI_URL}/\$/datasets" | grep -o "\"ds.name\" : \"/${DATASET_NAME}\""
