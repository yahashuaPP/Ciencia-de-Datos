{#
    Override estándar de dbt: sin esto, un modelo con +schema: silver se crearía como
    "<schema_del_target>_silver" (p.ej. SILVER_silver). Con este override, el esquema
    configurado en dbt_project.yml (silver, gold) o en seeds (bronze) se usa tal cual,
    para que los datos terminen exactamente en TAXI_DB.BRONZE / SILVER / GOLD.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}

        {{ default_schema }}

    {%- else -%}

        {{ custom_schema_name | trim }}

    {%- endif -%}

{%- endmacro %}
