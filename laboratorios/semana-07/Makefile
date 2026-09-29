DBT = dbt --project-dir dbt_taxi --profiles-dir dbt_taxi

.PHONY: setup ingest deps build docs pipeline full-refresh

setup:            ## Crea warehouse, DB, rol, esquemas, stage y tablas Bronze (idempotente)
	python -m infra.setup_snowflake

ingest:           ## Descarga los 20 meses de TLC y los carga en BRONZE
	python -m ingestion.run

deps:
	$(DBT) deps

build: deps       ## Seeds + modelos Silver/Gold + tests, en orden de dependencias
	$(DBT) build

docs:
	$(DBT) docs generate

pipeline: ingest build   ## Ejecución normal (re-ejecutable)

full-refresh: ingest deps   ## Reconstruye todo desde cero
	$(DBT) build --full-refresh
