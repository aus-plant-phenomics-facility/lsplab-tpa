select
   measurement_label as "experiment",
   snapshot.id,
   metadata_view."Plant Species" ||
   CASE
   WHEN "Treatment 1" = 'Control' THEN 'AA'
   WHEN "Treatment 1" = 'Salt' THEN 'BB'
   END
   || id_tag as "plant barcode",
   car_tag as "car tag",
   COALESCE(to_char(time_stamp, 'YYYY-MM-DD_HH24-MI-SS'), '') as "timestamp",
   weight_before as "weight before",
   weight_after as "weight after",
   water_amount as "water amount",
   completed,
   measurement_label as "measurement label",
   comment as tag,
   camera_label || measurement_label || '_' || id_tag || '_' || COALESCE(to_char(time_stamp, 'YYYY-MM-DD_HH24-MI-SS'), '') || '_resized;' as tiles
from
   snapshot
   join metadata_view on snapshot.id = metadata_view.snapshot_id
   join tiled_image on tiled_image.snapshot_id = snapshot.id
where camera_label = 'RGB SV1';