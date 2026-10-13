#!/bin/bash
echo "Generating TypeScript types from OpenAPI specification..."

npx openapi-typescript ../../docs/openapi.yaml -o ./generated/api.types.ts

echo "Types generated successfully at types/generated/api.types.ts"