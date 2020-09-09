select
   measurement_label as "experiment",
   snapshot.id,
   CASE 
   WHEN "Plant Species" is NULL THEN 'XX'
   ELSE SUBSTRING(metadata_view."Plant Species",0,3) 
   END
   ||
   "Replicate"
   ||
   SUBSTRING(metadata_view."Genotype ID",5,8)   
   ||
   CASE 
   WHEN "Treatment 1" = 'Control' THEN 'C'
   WHEN "Treatment 1" = 'Salt' THEN 'S'
   END
   || snapshot.id_tag as "plant barcode",
   car_tag as "car tag",
COALESCE(to_char(time_stamp, 'YYYY-MM-DD_HH12-MI-SS'), '') as "timestamp",
   weight_before as "weight before",
   weight_after as "weight after",
   water_amount as "water amount",
   completed,
   measurement_label as "measurement label",
   comment as tag,
   string_agg(camera_label || '_' || snapshot.id_tag || '_' || COALESCE(to_char(time_stamp, 'YYYY-MM-DD_HH12-MI-SS'), '') || ' resized',';') || ';' as tiles
from
   snapshot
   join metadata_view on snapshot.id_tag = metadata_view.id_tag
   join tiled_image on tiled_image.snapshot_id = snapshot.id
where camera_label like 'RGB SV%'
and measurement_label = '0270 MxK'
and "Genotype ID" like 'MxK%'
and snapshot.id_tag like '0%'
group by measurement_label, snapshot.id, "Plant Species", "Replicate", "Genotype ID", "Treatment 1"
;