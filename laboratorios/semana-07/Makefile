DBT = dbt --project-dir dbt_taxi --profiles-dir dbt_taxi
INGEST_ARGS ?=

.DEFAULT_GOAL := pipeline
.NOTPARALLEL:   # el orden setup -> ingest -> build es obligatorio; nunca en paralelo
.PHONY: setup ingest deps build docs pipeline full-refresh clean

setup:            ## Crea rol, warehouse, DB, esquemas, stage y tablas Bronze (idempotente)
	python -m infra.setup_snowflake

ingest:           ## Descarga los 20 meses de TLC y los carga en BRONZE (omite los ya cargados)
	python -m ingestion.run $(INGEST_ARGS)

deps:
	$(DBT) deps

build: deps       ## Seeds + modelos Silver/Gold + tests, en orden de dependencias
	$(DBT) build

docs:
	$(DBT) docs generate

pipeline: setup ingest build   ## Desde cero o día a día: setup (idempotente) + ingesta + dbt build

full-refresh: setup ingest deps   ## Reconstruye Silver/Gold desde Bronze (no toca Bronze)
	$(DBT) build --full-refresh

clean:            ## Limpia artefactos de dbt del volumen
	rm -rf dbt_taxi/target dbt_taxi/dbt_packages dbt_taxi/logs