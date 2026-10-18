# Shopping evidence API v2

## Data flow

Raw price/deal exports → quality filters → dated source series → past-only
benchmark and rolling evaluation → atomic assessment_snapshot.json → API →
badge and price-check receipt.

scripts/build_assessment_snapshot.py runs after the existing daily export.
A failed build does not overwrite the previous snapshot. Docker includes the
prebuilt snapshot: build the snapshot before building an image. A changed file
is validated and reloaded on the next request, without model training at runtime.

Source dates are not independently verified publication timestamps. Backtests
test the available dated records, not a fully timestamped point-in-time feed.

## GET /api/v2/assessment

Required: title (up to 500 characters).

Optional: price (positive finite THB), ambiguous, title_source, price_source.
Explicit confirmation uses confirmed=true, product=DDR4|DDR5|NVME|SATA|GPU
and either capacity_gb or model. SSD TB is decimal: 1 TB = 1000 GB.

Response: schema_version, dataset_version, dataset_asof, assessment_date,
product, product_match, price_assessment, seasonality, outlook, history,
channels, category_context, evidence, dashboard, dataset_warning.
Unsupported titles return covered=false. A missing initial snapshot returns 503;
invalid input returns 422. Unavailable values are JSON null, never NaN or zero.

Runtime option policy (v0.2.5): the extension selects the first enabled shop
option when none is selected, then pairs its identity and the product-area price.
variant_title and variant_label carry the resolved identity; the original title
is preserved. This is observed-page provenance, not manual user confirmation.
product_match.selection_note discloses the option. Missing option evidence,
price ranges and conflicting identities still require confirmation. Dataset
filtering and legacy parsers retain their conservative policies.

Price statuses: below / within / above / insufficient.
Outlook statuses: validated_forecast / scenario / unavailable.
Seasonal statuses: supported / historical_only.

Legacy /api/verdict, /api/series and health fields remain available. Health adds
dataset version, snapshot date and a last-good-reload warning. Legacy APIs keep
their old baseline calculations; new clients use v2.

## Models and limits

Current RAM/SSD references combine fresh retail, rolling level-corrected deal
and lagged driver candidates where available. Reliability weights use completed
preceding observed-target errors only. GPU uses matched model deal-day medians.
The GPU category index is separate, has index units, and cannot produce a model
price verdict.

Reference bands require 12 observed tests and use the preceding 24 absolute log
residuals (80th percentile). These are empirical bands, not guaranteed confidence
intervals. Forecast MAE is reported separately.

Staleness: GPU 30 days; RAM/SSD retail 45 days; deal 60 days; effective driver
age 90 days; FX 7 days. Runtime rechecks observation and FX age. Stale products
retain history and a clearly provisional historical-band comparison but lose
outlook. A single-source GPU benchmark
retains low confidence regardless of the number of tests.

Since extension v0.2.6, the price assessment is only a comparison against an
available positive THB reference band. It does not require seasonal/outlook
support, freshness, or additional validation-count gates at runtime. An old
reference/FX or unverified option sets price_assessment.provisional and warnings.
Missing price/band or unknown model still produces no comparison. Reference-band
construction and timing/forecast validation are unchanged.

Seasonality uses monthly medians of observed prices and within-year log-linear
detrending. Displayed years need at least 6 observed months. Eligibility requires
2 years with 9 months each, 9 overlapping months per held-out test, correlation
>=0.5 in every test, a complete aggregate profile, and >=5% profile range.
Favorable/less-favorable labels use the lowest/highest 4 months.
RX group labels are candidate context, not a claim of validated seasonality.

Outlook candidates: carry, damped trend, and trend with supported seasonal
adjustment. Trend fits log prices over 180 preceding days with 45-day damping
and a 1.5x trend-component cap. Scenarios require 6 recent observations.
Monthly observed origins evaluate 30/60/90 days on observed targets within
+/-7 days. Selection at each origin uses outcomes already completed then;
6 completed tests warm up selection. A horizon needs 12 subsequent tests and
>=5% lower MAE than carry on the same targets to pass. The 90-day test governs
the displayed forecast status. Overlapping rolling windows are disclosed.

Forecast bands use rolling forecast residuals, not reference residuals.
Scenario ranges use observed historical changes and are illustrative rather
than calibrated probabilities.

Historical display fills between first and last observation and applies EMA
30D. Raw points and gaps over 30 days are retained. Display fill does not enter
model fitting or evaluation. All displayed history is converted at snapshot FX,
not historical Thai quotes. Outlooks start at the last observed benchmark,
which may differ from the blended current reference midpoint.

Validation MAE remains in source units: USD/GB for RAM/SSD or USD/card for GPU;
the UI labels these explicitly. US references remain uncalibrated for Thailand.

## Verification and delivery

Python tests cover causal invariance, raw targets, staleness, confirmation,
snapshot replacement, currency conversion and API statuses. Node tests cover
parser parity cases, ranges, provenance, late replies, dismissal and retry.

Local-only browser preview uses a separate port (e.g. 8011). Screenshots are under
output/playwright/. Source and ZIP are prepared for manual testing; browser
installation and production deployment are separate, unperformed actions.
