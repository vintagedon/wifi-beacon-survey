-- ============================================================================
-- Pilot analytical views (schema wifi-beacon-survey/pilot-derived/1)
-- ============================================================================
-- These views are the provisional analytical contract documented in
-- docs/pilot-analysis-contract.md. They are rebuilt from the versioned
-- per-run Parquet layer on every update; nothing here is durable state and
-- none of it is a PostgreSQL schema.
--
-- Staging tables (stg_*) are created by pilot_database.py directly from the
-- Parquet artifacts and hold source grain. The pilot_* views are the stable
-- public surface required by the contract.
--
-- Trend discipline: stg_run_health.in_trend is true only for completed-sweep
-- pilot-series attempts. Commissioning runs are visible in health and in
-- pilot_runs but contribute zero rows to every trend denominator.

-- ----------------------------------------------------------------------------
-- Base views: source grain preserved, provenance intact.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW pilot_runs AS
SELECT
    run_id,
    source_path,
    classification,
    attempt_state,
    run_status,
    started_utc,
    eligible,
    input_complete,
    extraction_status,
    error,
    derived_schema_id,
    extractor_version,
    tshark_version
FROM stg_run;

CREATE OR REPLACE VIEW pilot_frequencies AS
SELECT
    run_id, band, frequency_mhz, channel, regulatory_state, sample_status,
    dwell_seconds, pcap_file, bssid_count, beacon_count, error
FROM stg_frequencies;

CREATE OR REPLACE VIEW pilot_observations AS
SELECT
    run_id, band, frequency_mhz, channel, bssid, ssid, beacons,
    beacon_interval_tu, rssi_min_dbm, rssi_mean_dbm, rssi_max_dbm,
    first_seen, last_seen, beacon_reception_ratio
FROM stg_observations;

CREATE OR REPLACE VIEW pilot_ie_capabilities AS
SELECT
    run_id, bssid, elements, ext_elements,
    has_ht, has_vht, has_he, has_he_6ghz, has_eht, has_mld,
    has_multiple_bssid, has_rnr, has_bss_load, has_rsn,
    has_extended_capabilities
FROM stg_ie_capabilities;

CREATE OR REPLACE VIEW pilot_rnr AS
SELECT
    run_id, pcap_file, frame_number, frame_time_epoch, tx_bssid, tx_ssid,
    op_class, channel, neighbor_bssid, short_ssid, bss_params,
    mld_link_id, mld_id, disabled_link, target_band, target_frequency_mhz,
    structure_status, unpaired_fields, field_resolution_state,
    raw_op_class, raw_channel, raw_neighbor_bssid, raw_short_ssid,
    raw_bss_params, raw_mld_link_id, raw_mld_id, raw_disabled_link
FROM stg_rnr;

CREATE OR REPLACE VIEW pilot_bss_load AS
SELECT
    run_id, pcap_file, frame_number, frame_time_epoch, bssid, ssid,
    station_count, utilization, admission_capacity,
    raw_station_count, raw_utilization, raw_admission_capacity
FROM stg_bss_load;

CREATE OR REPLACE VIEW pilot_field_resolution AS
SELECT
    run_id, logical_name, status, resolved_field, candidates
FROM stg_field_resolution;

-- ----------------------------------------------------------------------------
-- Collection health: every eligible attempt and every expected slot,
-- including skipped, failed, running, malformed, and missing hours.
-- Commissioning runs appear with in_trend = false.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW pilot_run_health AS
SELECT
    h.run_id,
    h.state,
    h.eligible,
    h.in_trend,
    h.reason,
    h.started_utc,
    h.input_complete,
    r.extraction_status
FROM stg_run_health h
LEFT JOIN stg_run r USING (run_id);

-- ----------------------------------------------------------------------------
-- Longitudinal metrics. Denominators are explicit columns: a ratio in the
-- briefing names its numerator and denominator from these rows.
-- Trend rows only (in_trend): commissioning and non-success runs excluded.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW pilot_hourly_metrics AS
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
    FROM stg_frequencies
    GROUP BY run_id
),
obs AS (
    SELECT
        run_id,
        COUNT(DISTINCT bssid)   AS observed_bssids,
        COALESCE(SUM(beacons), 0) AS beacon_frames,
        ROUND(AVG(rssi_mean_dbm), 1) AS mean_rssi_dbm,
        MIN(rssi_min_dbm)       AS min_rssi_dbm,
        MAX(rssi_max_dbm)       AS max_rssi_dbm
    FROM stg_observations
    GROUP BY run_id
)
SELECT
    f.run_id,
    h.started_utc,
    COALESCE(o.observed_bssids, 0)        AS observed_bssids,
    COALESCE(o.beacon_frames, 0)          AS beacon_frames,
    f.sampled_frequencies,
    f.sampled_empty_frequencies,
    f.regulatory_skips,
    f.capture_errors,
    f.manifest_frequencies,
    o.mean_rssi_dbm,
    o.min_rssi_dbm,
    o.max_rssi_dbm
FROM freq f
JOIN stg_run_health h USING (run_id)
LEFT JOIN obs o USING (run_id)
WHERE h.in_trend;

CREATE OR REPLACE VIEW pilot_band_metrics AS
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
    FROM stg_frequencies
    GROUP BY run_id, band
),
obs AS (
    SELECT
        run_id,
        band,
        COUNT(DISTINCT bssid)     AS observed_bssids,
        COALESCE(SUM(beacons), 0) AS beacon_frames
    FROM stg_observations
    GROUP BY run_id, band
)
SELECT
    f.run_id,
    f.band,
    COALESCE(o.observed_bssids, 0) AS observed_bssids,
    COALESCE(o.beacon_frames, 0)   AS beacon_frames,
    f.populated_frequencies,
    f.sampled_empty_frequencies,
    f.regulatory_skips,
    f.capture_errors,
    f.attempted_frequencies
FROM freq f
JOIN stg_run_health h USING (run_id)
LEFT JOIN obs o ON o.run_id = f.run_id AND o.band = f.band
WHERE h.in_trend;

-- ----------------------------------------------------------------------------
-- Capability advertisements. Denominator is the count of observed BSSIDs
-- (capability rows) for the run. "Advertises" describes what the AP sent.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW pilot_capability_metrics AS
SELECT
    c.run_id,
    h.started_utc,
    COUNT(*)                                   AS observed_bssids,
    COUNT(*) FILTER (WHERE c.has_he)           AS advertises_he,
    COUNT(*) FILTER (WHERE c.has_he_6ghz)      AS advertises_he_6ghz,
    COUNT(*) FILTER (WHERE c.has_eht)          AS advertises_eht,
    COUNT(*) FILTER (WHERE c.has_mld)          AS advertises_mld,
    COUNT(*) FILTER (WHERE c.has_multiple_bssid)
                                               AS advertises_multiple_bssid,
    COUNT(*) FILTER (WHERE c.has_rnr)          AS carries_rnr,
    COUNT(*) FILTER (WHERE c.has_bss_load)     AS carries_bss_load,
    COUNT(*) FILTER (WHERE c.has_vht)          AS advertises_vht,
    COUNT(*) FILTER (WHERE c.has_ht)           AS advertises_ht,
    COUNT(*) FILTER (WHERE c.has_rsn)          AS carries_rsn,
    COUNT(*) FILTER (WHERE c.has_extended_capabilities)
                                               AS carries_extended_capabilities
FROM stg_ie_capabilities c
JOIN stg_run_health h USING (run_id)
WHERE h.in_trend
GROUP BY c.run_id, h.started_utc;

-- ----------------------------------------------------------------------------
-- 6 GHz evidence. Direct beacon observations, sampled-empty frequencies,
-- RNR-advertised 6 GHz neighbors (single-occurrence rows only -- repeated
-- values are never paired positionally), disabled links, ambiguous rows,
-- unresolved operating classes, and nonconcurrent advertised-but-not-
-- observed cases. No positive 6 GHz control exists on this instrument, so
-- the nonconcurrency reading is provisional pending the falsification test.
-- A non-observation here is not evidence that the receiver is calibrated
-- for 6 GHz.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW pilot_6ghz_evidence AS
WITH trend_runs AS (
    SELECT run_id, started_utc FROM stg_run_health WHERE in_trend
),
direct AS (
    SELECT
        o.run_id,
        COUNT(DISTINCT o.bssid) AS direct_bssids,
        COALESCE(SUM(o.beacons), 0) AS direct_beacons
    FROM stg_observations o
    JOIN trend_runs t USING (run_id)
    WHERE o.band = '6GHz'
    GROUP BY o.run_id
),
freq_state AS (
    SELECT
        f.run_id,
        COUNT(*) FILTER (WHERE f.sample_status = 'sampled')
            AS sampled_frequencies,
        COUNT(*) FILTER (WHERE f.sample_status = 'sampled_empty')
            AS sampled_empty_frequencies,
        COUNT(*) AS manifest_frequencies
    FROM stg_frequencies f
    JOIN trend_runs t USING (run_id)
    WHERE f.band = '6GHz'
    GROUP BY f.run_id
),
rnr_state AS (
    SELECT
        r.run_id,
        -- Only safely paired single-occurrence rows may assert a neighbor.
        COUNT(DISTINCT CASE
            WHEN r.structure_status = 'single_occurrence'
                 AND r.target_band = '6GHz'
            THEN r.tx_bssid || '>' || r.neighbor_bssid END)
            AS advertised_6ghz_neighbors,
        COUNT(DISTINCT CASE
            WHEN r.structure_status = 'single_occurrence'
                 AND r.target_band = '6GHz'
                 AND r.disabled_link IS NOT NULL
                 AND r.disabled_link IN ('True', 'true', '1')
            THEN r.tx_bssid || '>' || r.neighbor_bssid END)
            AS advertised_6ghz_disabled_links,
        COUNT(DISTINCT CASE
            WHEN r.structure_status = 'single_occurrence'
                 AND r.target_band = 'unknown'
            THEN r.tx_bssid || '>' || r.neighbor_bssid END)
            AS unresolved_operating_classes,
        COUNT(*) FILTER (
            WHERE r.structure_status = 'unpaired_multi_occurrence')
            AS ambiguous_rows
    FROM stg_rnr r
    JOIN trend_runs t USING (run_id)
    GROUP BY r.run_id
),
advertised AS (
    SELECT DISTINCT r.run_id, r.neighbor_bssid
    FROM stg_rnr r
    JOIN trend_runs t USING (run_id)
    WHERE r.structure_status = 'single_occurrence'
      AND r.target_band = '6GHz'
      AND r.neighbor_bssid IS NOT NULL
      AND (r.disabled_link IS NULL OR r.disabled_link NOT IN ('True', 'true', '1'))
),
not_observed AS (
    SELECT
        a.run_id,
        COUNT(DISTINCT a.neighbor_bssid) AS advertised_not_observed
    FROM advertised a
    LEFT JOIN stg_observations o
        ON o.run_id = a.run_id AND o.bssid = a.neighbor_bssid
    WHERE o.bssid IS NULL
    GROUP BY a.run_id
)
SELECT
    t.run_id,
    t.started_utc,
    COALESCE(d.direct_bssids, 0)          AS direct_bssids,
    COALESCE(d.direct_beacons, 0)         AS direct_beacons,
    COALESCE(fs.sampled_frequencies, 0)   AS sampled_frequencies,
    COALESCE(fs.sampled_empty_frequencies, 0)
                                          AS sampled_empty_frequencies,
    COALESCE(fs.manifest_frequencies, 0)  AS manifest_frequencies,
    COALESCE(rs.advertised_6ghz_neighbors, 0)
                                          AS advertised_6ghz_neighbors,
    COALESCE(rs.advertised_6ghz_disabled_links, 0)
                                          AS advertised_6ghz_disabled_links,
    COALESCE(rs.unresolved_operating_classes, 0)
                                          AS unresolved_operating_classes,
    COALESCE(rs.ambiguous_rows, 0)        AS ambiguous_rnr_rows,
    COALESCE(no.advertised_not_observed, 0)
                                          AS advertised_not_observed_nonconcurrent
FROM trend_runs t
LEFT JOIN direct d USING (run_id)
LEFT JOIN freq_state fs USING (run_id)
LEFT JOIN rnr_state rs USING (run_id)
LEFT JOIN not_observed no USING (run_id);
