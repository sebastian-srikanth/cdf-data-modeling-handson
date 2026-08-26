select
  cast(`assetExternalId` as STRING)                     as externalId,
  cast(`name`            as STRING)                     as name,
  cast(`description`     as STRING)                     as description,
  case
    when `parentExternalId` is null or trim(`parentExternalId`) = '' then null
    else node_reference('{{ instance_space }}', `parentExternalId`)
  end                                                   as parent,
  array(cast(`assetClass` as STRING))                   as tags
from `{{ raw_db }}`.`rwt_Training_TRN_Assets`
