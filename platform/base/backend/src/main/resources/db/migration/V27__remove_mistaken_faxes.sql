-- V26 created a separate "faxes" table by mistake (the request was to add a fax number to companies). Remove it.
DROP TABLE IF EXISTS faxes;
