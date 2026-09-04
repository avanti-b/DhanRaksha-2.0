# data/

Runtime data. Both file types below are gitignored.

## `dhanraksha.db`

The SQLite database, created automatically on first run. Holds scored
transactions and fraud cases. Delete it to start from an empty store.

## `creditcard.csv`

The Kaggle dataset — **not included**, as it is 144 MB and not ours to
redistribute.

Download from <https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud> and
place `creditcard.csv` here.

Needed only for:

- retraining (`python -m ml.train`)
- the "Load a dataset sample" button in the prediction UI

The application runs fine without it — trained artifacts ship in
`ml/artifacts/`.
