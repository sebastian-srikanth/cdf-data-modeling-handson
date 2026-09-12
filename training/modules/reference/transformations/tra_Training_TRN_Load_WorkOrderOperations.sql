-- Work-order operations: the individual jobs that make up one work order.
--
-- This is the only transformation in the course that joins two RAW tables, and
-- every clause below exists because the naive version of it failed in a
-- specific, silent way. Chapter 05 §5.6 walks through each failure in turn.
-- Read the comments as a checklist for your own transformations.

with ops as (
  select
    -- An external ID assembled with concat() becomes NULL the moment ANY part
    -- is NULL — and a NULL external ID fails ingestion without an error you
    -- would notice. nullif(trim(...), '') turns the blank cells RAW hands us
    -- into real NULLs so the filter below can catch them.  (§5.6.3)
    -- lpad restores the leading zeros RAW stripped. A CSV cell of 0010 is
    -- inferred as the INTEGER 10 on upload, so a plain cast gives "10" and your
    -- external IDs stop matching the source system.  (§5.6.4)
    concat(
      nullif(trim(cast(o.`workOrderNumber` as STRING)), ''),
      '-',
      lpad(nullif(trim(cast(o.`operationNumber` as STRING)), ''), 4, '0')
    )                                                         as opExternalId,
    o.`key`                                                   as sourceKey,
    nullif(trim(cast(o.`workOrderNumber` as STRING)), '')     as workOrderNumber,
    nullif(trim(cast(o.`tagExternalId`   as STRING)), '')     as tagExternalId,
    cast(o.`description`   as STRING)                         as opDescription,
    cast(o.`durationHours` as DOUBLE)                         as durationHours,
    cast(o.`craft`         as STRING)                         as craft,
    -- LEFT JOIN, not INNER. An INNER JOIN here silently deletes every
    -- operation whose work order is missing from the source table — no error,
    -- no warning, just a smaller row count than you expected.  (§5.6.1)
    cast(w.`title` as STRING)                                 as workOrderTitle
  from      `{{ raw_db }}`.`rwt_Training_TRN_WorkOrderOperations` o
  left join `{{ raw_db }}`.`rwt_Training_TRN_WorkOrders`         w
         on o.`workOrderNumber` = w.`workOrderNumber`
),

deduped as (
  -- Two source rows can describe the same operation — here, an original and a
  -- revision. They collapse onto one external ID, and CDF rejects the whole
  -- batch with "Duplicate node externalIds for space". DISTINCT cannot help:
  -- the rows genuinely differ. Pick a winner explicitly.  (§5.6.2)
  select
    *,
    row_number() over (partition by opExternalId order by sourceKey desc) as rn
  from ops
  where opExternalId is not null
)

select
  opExternalId                                                  as externalId,
  concat('Operation ', opExternalId)                            as name,
  opDescription                                                 as description,
  -- A reference is formed even when the target does not exist. This is
  -- deliberate: Chapter 16 teaches you to find the ones that dangle.  (§16.2)
  array(node_reference('{{ instance_space }}', tagExternalId))  as assets
from deduped
where rn = 1
