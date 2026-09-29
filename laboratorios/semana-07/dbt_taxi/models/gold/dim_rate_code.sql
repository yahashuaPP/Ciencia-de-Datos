{#
    GOLD - dim_rate_code: catálogo estático de tarifas (RatecodeID), según el Data Dictionary
    oficial de la TLC.
#}

select column1 as rate_code_id, column2 as rate_code_description
from (
    values
        (1, 'Standard rate'),
        (2, 'JFK'),
        (3, 'Newark'),
        (4, 'Nassau or Westchester'),
        (5, 'Negotiated fare'),
        (6, 'Group ride'),
        (99, 'Unknown')
)
