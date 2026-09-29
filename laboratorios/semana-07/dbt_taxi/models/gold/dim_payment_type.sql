{#
    GOLD - dim_payment_type: catálogo estático de medios de pago (payment_type), según el
    Data Dictionary oficial de la TLC.
#}

select column1 as payment_type_id, column2 as payment_type_description
from (
    values
        (0, 'Flex Fare trip'),
        (1, 'Credit card'),
        (2, 'Cash'),
        (3, 'No charge'),
        (4, 'Dispute'),
        (5, 'Unknown'),
        (6, 'Voided trip')
)
