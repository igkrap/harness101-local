-- Which things are kept by numbered lots is the definitions' to say (stock.lotWhen), no longer a fixed code group the framework
-- looks for: the stock screens of a project whose item screen chose from STOCK_TRACKING say so in those words.
UPDATE app_definitions d
SET definition = jsonb_set(d.definition::jsonb, '{stock,lotWhen}', jsonb_build_object('field', f.field ->> 'name', 'is', '["LOT"]'::jsonb))::text
FROM app_definitions i, LATERAL jsonb_array_elements(i.definition::jsonb -> 'fields') AS f(field)
WHERE jsonb_typeof(d.definition::jsonb -> 'stock') = 'object'
  AND i.entity_key = d.definition::jsonb -> 'stock' ->> 'itemEntity'
  AND f.field ->> 'codeGroup' = 'STOCK_TRACKING'
  AND COALESCE(jsonb_typeof(d.definition::jsonb -> 'stock' -> 'lotWhen'), 'null') = 'null';
