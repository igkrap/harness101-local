-- Documents (header + lines, e.g. an order): the lines live inside the row's data; the status is its own column.
ALTER TABLE app_records ADD COLUMN status VARCHAR(30);
