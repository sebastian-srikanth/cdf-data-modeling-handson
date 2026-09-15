select
  cast(`tsExternalId`  as STRING)                                as externalId,
  cast(`name`          as STRING)                                as name,
  cast(`description`   as STRING)                                as description,
  'numeric'                                                      as type,
  cast(`isStep`        as BOOLEAN)                               as isStep,
  cast(`sourceUnit`    as STRING)                                as sourceUnit,
  array(node_reference('{{ instance_space }}', `tagExternalId`)) as assets
from `{{ raw_db }}`.`rwt_Training_TRN_TimeSeries`
