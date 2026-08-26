select
  cast(`workOrderNumber` as STRING)                              as externalId,
  cast(`workOrderNumber` as STRING)                              as workOrderNumber,
  cast(`title`           as STRING)                              as name,
  cast(`description`     as STRING)                              as description,
  upper(trim(cast(`status` as STRING)))                          as status,
  cast(`orderType`       as STRING)                              as orderType,
  cast(`priority`        as INT)                                 as priority,
  cast(`actualCost`      as DOUBLE)                              as actualCost,
  nullif(trim(cast(`currency` as STRING)), '')                   as currency,
  'SAP-PM-TRAINING'                                              as sourceSystem,
  to_timestamp(`plannedStart`)                                   as scheduledStartTime,
  to_timestamp(`plannedEnd`)                                     as scheduledEndTime,
  array(node_reference('{{ instance_space }}', `tagExternalId`)) as assets
from `{{ raw_db }}`.`rwt_Training_TRN_WorkOrders`
