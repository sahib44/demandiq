# Phase 1 data pipeline

The entry points are `scripts/download_data.py` and `scripts/ingest_data.py`. File ingestion works without PostgreSQL; `--persist` optionally registers the verified dataset metadata, report and complete product catalogue. Field definitions are in [the data dictionary](DATA_DICTIONARY.md). No forecasting, weekly aggregation or inventory calculation occurs here.

## Acquire or supply a source

After the [README setup](../README.md#local-setup), run from the repository root:

```bash
python -m scripts.download_data
python -m scripts.ingest_data --input 'data/raw/uci-online-retail/Online Retail.xlsx'
```

The downloader uses the [official UCI ZIP](https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip). Its default destination contains `online-retail.zip`, `Online Retail.xlsx` and `source.json`; the JSON records URL, observed ZIP/workbook SHA-256, byte sizes, citation and license. Initial acquisition trusts the HTTPS source and records its observed digests. To pin a previously verified archive, set `UCI_ARCHIVE_SHA256` to your retained 64-hex digest and run:

```bash
python -m scripts.download_data --expected-sha256 "$UCI_ARCHIVE_SHA256"
```

The pin checks the **ZIP** digest, not the workbook digest. An existing source cache is reused only after checking its official URL and both file hashes against `source.json`, plus the optional supplied ZIP pin. An incomplete or corrupt cache fails visibly; use a new `--raw-dir` rather than silently replacing it. The first acquisition does not ship an independently authenticated reference digest. Checksums verify recorded content integrity, not immunity to an attacker rewriting both files and manifests.

Downloads have a bounded retry count and per-request timeout (`--attempts`, default 3, allowed 1–5; `--timeout`, default 60 seconds). Retryable network errors, HTTP 408/429 and server errors are retried. A 50 MiB archive limit, 100 MiB extracted-workbook limit and an expected-single-member ZIP rule bound extraction. Only the expected workbook name is written, never archive-supplied paths. A temporary sibling directory is renamed to the final cache after completion; failed staging directories are removed.

For a privately held local source, supply an XLSX or UTF-8 CSV directly:

```bash
python -m scripts.ingest_data --input /path/to/private/transactions.csv
```

The local file must obey the same eight-field schema. Its SHA-256 is computed before reading and checked again after reading to detect a changing input. The source-file digest and format identify its provenance; supplying a local file does not establish that it came from UCI. The official download's ZIP provenance remains in the raw cache; processed manifests identify their actual input-file digest.

`DEMANDIQ_DATA_DIR` defaults to `data`; the downloader uses its `raw/` directory and ingestion uses its `processed/` directory. `--raw-dir` and `--output-dir` override those respective roots. CLI tools read environment variables directly; copying `.env.example` alone does not load `.env` into a shell.

## Cleaning and classification

1. Validate the exact eight unique source headers. XLSX uses the first worksheet; CSV preserves strings and detects unequal row widths. Invalid required headers fail the whole import without exposing cell values.
2. Identify exact source duplicates across all eight fields before whitespace, identifier, date or numeric normalization. Keep the first occurrence. Source identities distinguish strings, integers, reals and booleans; source null markers are treated as missing equivalents and floating NaNs as equivalents. Thus a whitespace variant or textual numeric variant is retained, even if normalization later produces equal output values. The rule acts on parsed cell values, not the original file's byte formatting. Unsupported object-valued cells are not deduplicated together by their string representation.
3. Normalize identifiers and text. Trim surrounding whitespace, remove numeric identifier `.0` suffixes and normalize integral numeric identifiers to text. Preserve alphanumeric merchandise codes and leading zeros in textual identifiers. Limit normalized product IDs to 128 Unicode characters. Missing invoice/product IDs or malformed required identifiers reject the row. Missing or malformed optional description/customer/country values become null with flags; valid demand volume remains eligible.
4. Parse only documented naive date forms. Interpret explicit slash-separated strings as **day first**, retain London wall time and infer no UTC or daylight-saving conversion. Reject timezone-aware values, unknown formats, impossible dates/clocks and values outside pandas nanosecond range. See [accepted formats](DATA_DICTIONARY.md#source-table).
5. Require a nonzero integral signed-int64 quantity and finite strictly positive price. Booleans are invalid numeric values. Numeric strings are explicitly coerced and flagged. Preserve extreme valid quantities; do not clip, winsorize or infer corrected values.
6. Reject these accounting/postage/fee/manual codes, case-insensitively after trimming: `AMAZONFEE`, `BANK CHARGES`, `C2`, `CRUK`, `D`, `DOT`, `M`, `POST`, `S`. All other otherwise valid alphanumeric stock codes remain eligible. This explicit default list is a modeling policy rather than a claim of perfect merchandise classification.
7. Normalize a lowercase invoice prefix `c` to `C`. A valid C-prefixed negative movement enters **cancellations**; another negative movement enters **returns**; an ordinary positive movement enters **purchases**. A C-prefixed positive quantity is rejected as a sign mismatch. Invalid price/date/quantity/identifier or merchandise eligibility takes precedence over admission to any partition.
8. Replace normalized customer IDs with `SHA256(b"demandiq:uci-online-retail:customer:v1" + bytes([0]) + customer_id.encode("utf-8"))`; `bytes([0])` is one NUL separator byte. The source ID does not enter output tables, audits or logs. Produce typed accepted partitions, an audit entry for every row and the aggregate report.

Cancellations and returns are invoice/quantity signals. Phase 1 does not match them to purchases, prove physical goods were returned, reconstruct inventory movement, allocate original sale prices or infer return lags. Signed quantities remain available for later analysis; no cancellation is subtracted twice or silently converted into positive demand.

The domain prefix is fixed, public and deterministic, rather than a secret salt. Pseudonyms permit known-customer counting but remain linkable and susceptible to dictionary matching of a small identifier space. They are **not anonymous data**. Raw files, accepted partitions, audits and quality artifacts remain ignored private local files. Do not publish them, real customer information or transaction screenshots. Missing customer IDs are retained as null rather than inventing identities or dropping their sales.

## Reason-code catalogue

Every audit has one disposition (`duplicate`, `rejected`, `purchase`, `cancellation` or `return`) and a sorted `|`-delimited set of codes. Codes explain decisions without repeating source values.

| Codes | Meaning / effect |
| --- | --- |
| `exact_source_duplicate` | Later exact source copy; excluded before normalization; its only audit code |
| `missing_invoice_id`, `missing_product_id` | Required identifier absent; reject |
| `invalid_invoice_id`, `invalid_product_id` | Required identifier malformed; reject |
| `product_id_too_long` | Normalized product ID exceeds 128 characters; also `invalid_product_id`; reject |
| `missing_customer_id`, `invalid_customer_id` | Optional customer ID absent or malformed; null pseudonym, retain if otherwise valid |
| `missing_description`, `missing_country` | Optional text absent; null, retain if otherwise valid |
| `invalid_description`, `invalid_country` | Optional value is nontext; null, retain if otherwise valid |
| `invoice_id_trimmed`, `product_id_trimmed`, `customer_id_trimmed` | Removed surrounding whitespace from a nonempty identifier |
| `invoice_id_numeric_normalized`, `product_id_numeric_normalized`, `customer_id_numeric_normalized` | Integral numeric ID converted to text, or text `.0` suffix removed |
| `description_trimmed`, `country_trimmed` | Removed surrounding whitespace from nonempty optional text |
| `invoice_prefix_normalized` | Lowercase leading invoice `c` converted to `C` |
| `customer_pseudonymized` | Available normalized customer ID replaced with domain-separated SHA-256 |
| `invalid_quantity` | Missing, boolean, unsupported, nonfinite, fractional, zero or out-of-int64 quantity; reject |
| `quantity_trimmed`, `quantity_numeric_coerced` | Numeric source text trimmed and/or parsed |
| `quantity_integral_normalized` | Valid integral noninteger-type numeric quantity converted to int64 |
| `invalid_price` | Missing, boolean, unsupported, nonfinite, nonpositive or unrepresentable positive float64 price; reject |
| `price_trimmed`, `price_numeric_coerced` | Numeric price text trimmed and/or parsed |
| `price_float_normalized` | Valid native numeric price converted to float64 |
| `date_trimmed` | Removed surrounding whitespace from date text |
| `date_parsed_iso`, `date_parsed_day_first` | Parsed explicit supported string format |
| `date_native_normalized` | Python date or NumPy datetime converted to output datetime |
| `invalid_date` | Missing, unsupported, unparseable or out-of-range required date; reject |
| `timezone_aware_date` | Native datetime has timezone information; also `invalid_date`; reject |
| `nonmerchandise_code` | Explicit excluded stock code; reject |
| `cancellation_sign_mismatch` | C-prefixed invoice has positive quantity; reject |
| `classified_purchase`, `classified_cancellation`, `classified_return` | Accepted partition decision |

Some normalization flags can occur on a record rejected for another field; they record the attempted decision, not proof of acceptance. Unsupported timezone **strings** fail the explicit format rule with `invalid_date`; `timezone_aware_date` specifically records a native timezone-aware value.

## Counts, conservation and publication

Disposition counts are mutually exclusive:

```text
original_rows = duplicate_rows + rejected_rows + cleaned_rows
cleaned_rows = purchase_rows + cancellation_rows + return_rows
audit rows = original_rows
```

Missing/invalid summary flags count **nonduplicate rows before rejection**. They can overlap and include records rejected for another reason. `reason_counts` counts audit rows containing each code and also overlaps. Entity counts, countries and date coverage use all accepted partitions and exclude null values from distinct counts. Sequential stages record before/after/removed counts; classification conserves rows while separating partitions. No unexplained row is silently discarded.

The immutable dataset ID is SHA-256 over canonical JSON containing the input-file SHA-256 and configuration (cleaning version, pipeline version and input format). Changing file bytes, format or policy version creates a different identity, even if some normalized values match. Files are written into a temporary sibling directory and published by a directory rename only when all outputs are present:

```text
data/processed/<dataset_id>/
  purchases.parquet
  cancellations.parquet
  returns.parquet
  audit.parquet
  quality.json
  manifest.json
```

The manifest records each artifact's SHA-256 and Parquet row count. Publication/reuse verifies expected manifest identity/configuration, exact artifact-name set, file hashes, Parquet row metadata, report totals and row conservation. An identical import reuses a verified immutable directory. Corrupt or incomplete completed directories fail visibly; choose a new output root after investigating. Temporary failed work is removed. A concurrent importer that loses the rename race verifies the winning dataset.

The manifest's `artifact_dir` is only `<dataset_id>`, relative to the chosen processed root. Moving an intact dataset directory preserves its identity, but a consumer must resolve it against the correct new root. PostgreSQL metadata does not discover or validate an arbitrary relocation automatically. Deterministic files contain no source absolute paths or wall-clock durations. CLI completion logs can report the chosen path, aggregate counts and measured duration, without raw records.

## Optional database registration

Run migrations against a dedicated configured PostgreSQL database, then register the files:

```bash
python -m alembic -c backend/alembic.ini upgrade head
python -m scripts.ingest_data --input 'data/raw/uci-online-retail/Online Retail.xlsx' --persist
```

`--persist` requires `DATABASE_URL`; omission requires no database. PostgreSQL receives the manifest/dataset metadata, quality report and all accepted product codes with their earliest known description. It receives no transaction rows or customer pseudonyms. An advisory transaction lock serializes registrations of the same dataset ID. Dataset, report and catalogue are committed together; an identical retry is idempotent and a conflicting existing payload fails.

Filesystem publication and PostgreSQL registration are separate transactions. A database failure leaves valid files available, and rerunning `--persist` retries registration after verifying them. The CLI reports success only after requested registration completes; file existence alone is not evidence of database persistence. Observed verification results belong in [Phase 1 results](PHASE1_RESULTS.md).
