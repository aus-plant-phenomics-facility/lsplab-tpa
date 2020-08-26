select
   measurement_label as "experiment",
   snapshot.id,
   SUBSTRING(metadata_view."Plant Species",0,3) ||
   CASE
   WHEN "Genotype ID" = 'Rupali' THEN '001'
   WHEN "Genotype ID" = 'Genesis 836' THEN '002'
   END
   ||
   CASE
   WHEN "Treatment 1" = '1' THEN 'AA'
   WHEN "Treatment 1" != '1' THEN 'BB'
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
   'C:\Users\George\Downloads\0224_PH_UA_ACPFG_Sutton_Atieno_Chickpea_pilot_1\plantdb\tpa_backup\0224_PH_UA_ACPFG_Sutton_Atieno_Chickpea_pilot_1\' || camera_label || '_' || id_tag || '_' || COALESCE(to_char(time_stamp, 'YYYY-MM-DD_HH24-MI-SS'), '') || ' resized;' as tiles
from
   snapshot
   join metadata_view on snapshot.id = metadata_view.snapshot_id
   join tiled_image on tiled_image.snapshot_id = snapshot.id
where camera_label = 'RGB SV1';