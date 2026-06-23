-- Enable the extensions Odin relies on and create its graph.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'odin') THEN
        PERFORM ag_catalog.create_graph('odin');
    END IF;
END $$;

-- App tables live in public; ag_catalog stays in the path so AGE's agtype resolves.
ALTER DATABASE odin SET search_path = public, ag_catalog;
