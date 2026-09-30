-- ============================================================================
-- Ingestion DDL: wifi_beacon_survey (schemas survey, archive, ingest, derived)
-- ============================================================================
-- Machine-enforced structure for docs/ingestion-contract.md. Idempotent to
-- apply: every statement is safe to re-run against an already-provisioned
-- database, and a second apply leaves the catalog identical to the first.
--
-- The survey and archive schemas carry identical base tables generated from
-- the one definition in the create_base_tables DO block below. Base tables
-- hold source values only: no derived columns, no normalisation beyond type
-- conversion, and no row is ever updated or deleted after commit. The
-- derived schema holds views only; there are no tables or materialised
-- views in this unit.
--
-- Apply with: psql -d wifi_beacon_survey -f sql/ingest/up.sql
-- Reverse with: psql -d <test database only> -f sql/ingest/down.sql
-- The down-script is tested against the test database only; no executor
-- ever runs it against wifi_beacon_survey.

-- ----------------------------------------------------------------------------
-- Schemas
-- ----------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS survey;
CREATE SCHEMA IF NOT EXISTS archive;
CREATE SCHEMA IF NOT EXISTS ingest;
CREATE SCHEMA IF NOT EXISTS derived;

-- ----------------------------------------------------------------------------
-- Base tables, one definition applied to survey and archive
-- ----------------------------------------------------------------------------

DO $base$
DECLARE
    schema_name text;
BEGIN
    FOREACH schema_name IN ARRAY ARRAY['survey', 'archive'] LOOP
        EXECUTE format($ddl$
            CREATE TABLE IF NOT EXISTS %I.runs (
                run_id                            text PRIMARY KEY,
                instrument_schema                 text NOT NULL,
                run_status                        text NOT NULL,
                skip_reason                       text,
                started_utc                       timestamptz,
                slot_utc_hour                     timestamptz NOT NULL,
                interface                         text,
                interface_present                 boolean NOT NULL DEFAULT false,
                phy                               text,
                regulatory_domain                 text,
                regulatory_domain_phy             text,
                regulatory_domain_declared        text,
                regulatory_domain_set_attempted   boolean,
                regulatory_domain_set_result      text,
                regulatory_domain_at_discovery    text,
                regulatory_domain_post_sweep      text,
                usb_bus                           text,
                usb_port                          text,
                usb_device                        text,
                usb_controller_pci                text,
                usb_speed_mbps                    integer,
                usb_driver                        text,
                capture_dwell_seconds             integer,
                capture_bands                     text,
                capture_snaplen                   integer,
                capture_bpf_filter                text,
                raw                               jsonb NOT NULL
            )$ddl$, schema_name);

        EXECUTE format($ddl$
            CREATE TABLE IF NOT EXISTS %I.frequencies (
                run_id              text NOT NULL REFERENCES %I.runs(run_id),
                source_row_ordinal  integer NOT NULL,
                band                text NOT NULL,
                frequency_mhz       integer NOT NULL,
                channel             integer NOT NULL,
                regulatory_state    text NOT NULL,
                sample_status       text NOT NULL,
                dwell_seconds       integer NOT NULL,
                pcap_file           text,
                bssid_count         integer,
                beacon_count        integer,
                error               text,
                PRIMARY KEY (run_id, source_row_ordinal)
            )$ddl$, schema_name, schema_name);

        EXECUTE format($ddl$
            CREATE TABLE IF NOT EXISTS %I.observations (
                run_id               text NOT NULL REFERENCES %I.runs(run_id),
                source_row_ordinal   integer NOT NULL,
                band                 text NOT NULL,
                frequency_mhz        integer NOT NULL,
                channel              integer NOT NULL,
                bssid                text NOT NULL,
                ssid                 text NOT NULL DEFAULT '',
                beacons              integer NOT NULL,
                beacon_interval_tu   integer,
                rssi_min_dbm         numeric,
                rssi_mean_dbm        numeric,
                rssi_max_dbm         numeric,
                first_seen           timestamptz,
                last_seen            timestamptz,
                beacon_reception_ratio numeric,
                PRIMARY KEY (run_id, source_row_ordinal)
            )$ddl$, schema_name, schema_name);

        EXECUTE format($ddl$
            CREATE INDEX IF NOT EXISTS %I_frequencies_run_band
                ON %I.frequencies (run_id, band)$ddl$, schema_name, schema_name);

        EXECUTE format($ddl$
            CREATE INDEX IF NOT EXISTS %I_observations_run_band_freq
                ON %I.observations (run_id, band, frequency_mhz)$ddl$,
            schema_name, schema_name);
    END LOOP;
END
$base$;

-- ----------------------------------------------------------------------------
-- Ingest ledger: expected UTC slots, attempts, loads
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ingest.slots (
    slot_utc_hour   timestamptz PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS ingest.attempts (
    run_id                              text PRIMARY KEY,
    slot_utc_hour                       timestamptz NOT NULL
                                        REFERENCES ingest.slots(slot_utc_hour),
    started_utc                         timestamptz,
    instrument_schema                   text,
    run_status                          text,
    attempt_state                       text NOT NULL,
    disposition                         text NOT NULL,
    reason                              text,
    regulatory_domain                   text,
    regulatory_domain_phy               text,
    regulatory_domain_declared          text,
    regulatory_domain_set_result        text,
    regulatory_domain_at_discovery      text,
    regulatory_domain_post_sweep        text,
    interface_present                   boolean,
    phy                                 text,
    usb_device                          text
);

CREATE INDEX IF NOT EXISTS attempts_slot_idx
    ON ingest.attempts (slot_utc_hour);
CREATE INDEX IF NOT EXISTS attempts_disposition_idx
    ON ingest.attempts (disposition);

CREATE TABLE IF NOT EXISTS ingest.loads (
    load_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              text NOT NULL REFERENCES ingest.attempts(run_id),
    outcome             text NOT NULL,
    loader_version      text NOT NULL,
    sha256_instrument   text NOT NULL,
    sha256_frequencies  text NOT NULL,
    sha256_aggregate    text NOT NULL,
    loaded_at           timestamptz NOT NULL DEFAULT now()
);

-- At most one successful load per attempt; failed attempts may retry and
-- keep every failure record. A source_changed outcome never re-loads, so a
-- loaded attempt gains at most one source_changed row after its loaded row.
CREATE UNIQUE INDEX IF NOT EXISTS loads_one_loaded_per_attempt
    ON ingest.loads (run_id) WHERE outcome = 'loaded';

-- ----------------------------------------------------------------------------
-- Derived views. These read only base and ingest tables.
-- ----------------------------------------------------------------------------

-- Every expected UTC slot with its attempt states and dispositions. A slot
-- with no attempt at all is a no_run row: a gap with a reason, never zero.
CREATE OR REPLACE VIEW derived.slot_health AS
SELECT
    s.slot_utc_hour,
    COUNT(a.run_id)                          AS attempt_count,
    COALESCE(array_agg(DISTINCT a.attempt_state)
        FILTER (WHERE a.run_id IS NOT NULL), '{}')  AS attempt_states,
    COALESCE(array_agg(DISTINCT a.disposition)
        FILTER (WHERE a.run_id IS NOT NULL), '{}')  AS dispositions,
    CASE WHEN COUNT(a.run_id) = 0 THEN 'no_run' ELSE 'covered' END
                                             AS slot_state
FROM ingest.slots s
LEFT JOIN ingest.attempts a ON a.slot_utc_hour = s.slot_utc_hour
GROUP BY s.slot_utc_hour;

-- Per survey-run metrics. Definitions match the legacy pilot_hourly_metrics
-- so the gate 1.5 cross-check compares like with like: observed_bssids is
-- COUNT(DISTINCT bssid) over the run's observations; beacon_frames is
-- COALESCE(SUM(beacons), 0); mean_rssi_dbm is ROUND(AVG(rssi_mean_dbm), 1)
-- over the non-null per-observation means; the frequency outcome counts are
-- manifest rows grouped by sample_status, with manifest_frequencies the row
-- total.
CREATE OR REPLACE VIEW derived.run_metrics AS
WITH freq AS (
    SELECT
        run_id,
        COUNT(*) FILTER (WHERE sample_status = 'sampled')
            AS sampled_frequencies,
        COUNT(*) FILTER (WHERE sample_status = 'sampled_empty')
            AS sampled_empty_frequencies,
        COUNT(*) FILTER (WHERE sample_status = 'regulatory_skip')
            AS regulatory_skips,
        COUNT(*) FILTER (WHERE sample_status = 'capture_error')
            AS capture_errors,
        COUNT(*) AS manifest_frequencies
    FROM survey.frequencies
    GROUP BY run_id
),
obs AS (
    SELECT
        run_id,
        COUNT(DISTINCT bssid)      AS observed_bssids,
        COALESCE(SUM(beacons), 0)  AS beacon_frames,
        ROUND(AVG(rssi_mean_dbm), 1) AS mean_rssi_dbm,
        MIN(rssi_min_dbm)          AS min_rssi_dbm,
        MAX(rssi_max_dbm)          AS max_rssi_dbm
    FROM survey.observations
    GROUP BY run_id
)
SELECT
    r.run_id,
    r.started_utc,
    COALESCE(o.observed_bssids, 0)   AS observed_bssids,
    COALESCE(o.beacon_frames, 0)     AS beacon_frames,
    f.sampled_frequencies,
    f.sampled_empty_frequencies,
    f.regulatory_skips,
    f.capture_errors,
    f.manifest_frequencies,
    o.mean_rssi_dbm,
    o.min_rssi_dbm,
    o.max_rssi_dbm
FROM survey.runs r
JOIN freq f USING (run_id)
LEFT JOIN obs o USING (run_id);

-- Per survey-run and band coverage. attempted_frequencies counts every
-- manifest row in the band, matching the legacy band metric's denominator;
-- a regulatory-skip row is a recorded attempt that was refused at dwell 0,
-- not an unlisted frequency.
CREATE OR REPLACE VIEW derived.band_coverage AS
WITH freq AS (
    SELECT
        run_id,
        band,
        COUNT(*) FILTER (WHERE sample_status = 'sampled')
            AS populated_frequencies,
        COUNT(*) FILTER (WHERE sample_status = 'sampled_empty')
            AS sampled_empty_frequencies,
        COUNT(*) FILTER (WHERE sample_status = 'regulatory_skip')
            AS regulatory_skips,
        COUNT(*) FILTER (WHERE sample_status = 'capture_error')
            AS capture_errors,
        COUNT(*) AS attempted_frequencies
    FROM survey.frequencies
    GROUP BY run_id, band
),
obs AS (
    SELECT
        run_id,
        band,
        COUNT(DISTINCT bssid)      AS observed_bssids,
        COALESCE(SUM(beacons), 0)  AS beacon_frames
    FROM survey.observations
    GROUP BY run_id, band
)
SELECT
    f.run_id,
    f.band,
    f.attempted_frequencies,
    f.populated_frequencies       AS sampled_frequencies,
    f.sampled_empty_frequencies,
    f.regulatory_skips,
    f.capture_errors,
    COALESCE(o.observed_bssids, 0) AS bssids,
    COALESCE(o.beacon_frames, 0)   AS beacons
FROM freq f
LEFT JOIN obs o ON o.run_id = f.run_id AND o.band = f.band;
