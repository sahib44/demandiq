# Data provenance and redistribution

Checked against the official source on **2026-10-23**.

- Creator: Daqing Chen.
- Citation: Chen, D. (2015). *Online Retail* [Dataset]. UCI Machine Learning Repository.
- DOI: https://doi.org/10.24432/C5BW33
- Dataset page: https://archive.ics.uci.edu/dataset/352/online+retail
- License: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
- Legal code: https://creativecommons.org/licenses/by/4.0/legalcode

UCI explicitly identifies CC BY 4.0. That license permits sharing and adaptation,
including commercial uses, with appropriate attribution, a license link and an
indication of changes. Attribution must not suggest endorsement. The license also
notes that privacy/publicity or other rights may require separate consideration.

This public repository deliberately does not redistribute the full workbook,
raw/processed transactions, customer IDs or pseudonyms, row audits, fitted models
or generated analytical bundles. They are downloaded/generated locally and
ignored by Git. This keeps the source checkout small and avoids republishing
customer-level data, despite the dataset's permission for attributed redistribution.

The download command, official URL and SHA-256 pin are documented in the root
README. Cleaning removes duplicates/quarantines invalid records, normalizes values,
separates credit movements, pseudonymizes customer IDs and aggregates weekly units.
These transformations are project choices, not changes endorsed by UCI or the
original retailer. Published aggregate results and screenshots retain this
attribution and are historical analytical/simulated outcomes.

`fixtures/synthetic_retail.csv` is entirely fictional and authored for this project.
It contains no UCI records or real customer identifiers. Its outputs must not be
presented as real model performance or company savings. The dataset's CC BY license
applies to the UCI data; it does not purport to license this project's software or
third-party dependencies. DemandIQ is independent and unaffiliated with UCI or the
historical retailer.
