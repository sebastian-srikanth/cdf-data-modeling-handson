select
  cast(`equipmentExternalId` as STRING)                   as externalId,
  cast(`name`                as STRING)                   as name,
  cast(`description`         as STRING)                   as description,
  cast(`manufacturer`        as STRING)                   as manufacturer,
  cast(`serialNumber`        as STRING)                   as serialNumber,
  node_reference('{{ instance_space }}', `tagExternalId`) as asset
from `{{ raw_db }}`.`rwt_Training_TRN_Equipment`
