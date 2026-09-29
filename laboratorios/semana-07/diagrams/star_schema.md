# Diagrama del esquema estrella (capa Gold)

**Grano de `fct_trips`**: un registro por viaje individual de yellow taxi.
`dim_location` cumple dos roles en el hecho (recogida y destino), por eso aparece dos veces
en el diagrama.

```mermaid
erDiagram
    FCT_TRIPS }o--|| DIM_DATE       : "pickup_date_key / dropoff_date_key"
    FCT_TRIPS }o--|| DIM_TIME       : "pickup_hour_key / dropoff_hour_key"
    FCT_TRIPS }o--|| DIM_LOCATION   : "pu_location_key (recogida)"
    FCT_TRIPS }o--|| DIM_LOCATION   : "do_location_key (destino)"
    FCT_TRIPS }o--|| DIM_VENDOR     : "vendor_key"
    FCT_TRIPS }o--|| DIM_RATE_CODE  : "rate_code_key"
    FCT_TRIPS }o--|| DIM_PAYMENT_TYPE : "payment_type_key"

    FCT_TRIPS {
        string trip_key PK
        int pickup_date_key FK
        int dropoff_date_key FK
        int pickup_hour_key FK
        int do_location_key FK
        int pu_location_key FK
        int vendor_key FK
        int rate_code_key FK
        int payment_type_key FK
        int passenger_count
        number trip_distance_miles
        int trip_duration_minutes
        string store_and_fwd_flag
        number fare_amount
        number extra_amount
        number mta_tax_amount
        number tip_amount
        number tolls_amount
        number improvement_surcharge_amount
        number congestion_surcharge_amount
        number airport_fee_amount
        number cbd_congestion_fee_amount
        number total_amount
    }

    DIM_DATE {
        int date_key PK
        date full_date
        int year
        int quarter
        int month
        string month_name
        int day_of_week
        string day_name
        boolean is_weekend
    }

    DIM_TIME {
        int hour_key PK
        int hour_of_day
        string am_pm
        string time_of_day_bucket
    }

    DIM_LOCATION {
        int location_id PK
        string borough
        string zone
        string service_zone
    }

    DIM_VENDOR {
        int vendor_id PK
        string vendor_name
    }

    DIM_RATE_CODE {
        int rate_code_id PK
        string rate_code_description
    }

    DIM_PAYMENT_TYPE {
        int payment_type_id PK
        string payment_type_description
    }
```

Detalle de columnas, tests (`not_null`, `unique`, `relationships`) y justificación de cada
transformación: `dbt_taxi/models/gold/_gold__models.yml` y los comentarios en cada `.sql`.
