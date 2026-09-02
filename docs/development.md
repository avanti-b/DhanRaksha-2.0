# Development guide

---

## Setup

Requires Python 3.11+.

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env

python -m backend.app
```

Open <http://localhost:5000>. Flask serves the API and the frontend together, so
there is no second process.

Trained artifacts ship in `ml/artifacts/`, so this works immediately. The 144 MB
`creditcard.csv` is only needed to retrain or to use the sample-loading button.

---

## Running things

```bash
python -m backend.app                    # dev server
FLASK_DEBUG=true python -m backend.app   # with reloader
pytest                                   # full suite (84 tests, ~4s)
pytest tests/test_risk_engine.py -v      # one file
pytest -k threshold                      # by name
docker compose up --build                # containerised
```

Always run modules from the project root with `python -m`. `PYTHONPATH` needs to
include the root so `backend` and `ml` are both importable — `python backend/app.py`
will fail on the `ml.preprocessing` import.

---

## Layout and where code belongs

| Change | Goes in |
|---|---|
| New endpoint | `backend/routes/` — parse, delegate, serialise, nothing else |
| Business logic | `backend/services/` |
| New risk rule | `backend/services/risk_engine.py` |
| Query or storage change | `backend/repositories/` |
| Input rules | `backend/schemas/validators.py` |
| Feature handling | `ml/preprocessing.py` — used by training *and* serving |
| New setting | `backend/config.py` plus `.env.example` |

The layering rule is that calls only go downward: routes → services →
repositories. A route importing a repository, or a service importing Flask, is a
mistake worth fixing on sight.

---

## Adding a risk rule

Rules live in `RiskEngine._evaluate_rules()`. Each is a `RiskRule` with a name, a
human-readable description, a weight, a trigger condition and a detail string.

```python
RiskRule(
    name="round_number_amount",
    description="Amount is an exact multiple of 100, a pattern seen in card testing",
    weight=0.03,
    triggered=amount > 0 and amount % 100 == 0,
    detail=f"amount={amount:.2f}",
)
```

Four things to respect:

1. **Weights add only.** Nothing subtracts risk. Total contribution is capped at
   0.25 so the model stays dominant.
2. **Thresholds should be measured.** If the rule needs a cutoff, derive it in
   `build_risk_reference()` in `ml/train.py` and read it from
   `self.reference`. Do not hardcode a plausible-looking number.
3. **The description is user-facing.** It appears in the detail drawer and in
   stored records. Write it for an analyst reading the case in six months.
4. **Test it.** Add a case to `tests/test_risk_engine.py` covering both trigger
   and non-trigger.

---

## Adding an endpoint

1. Add the handler to the appropriate blueprint in `backend/routes/`.
2. Validate input in `backend/schemas/validators.py`, raising `ValidationError`.
3. Put the logic in a service; the route should be a few lines.
4. Raise `ApiError` subclasses — `NotFoundError`, `ConflictError` — rather than
   returning error dictionaries by hand. The handlers in `errors.py` render them.
5. Test the success path, one validation failure, and one not-found.

Never return a raw exception message to a client. `errors.py` handles that
centrally: unexpected exceptions are logged with a traceback and an incident ID,
and the client receives the ID only.

---

## Swapping the database (Milestone 2 preview)

1. Implement `TransactionRepository` and `CaseRepository` from
   `repositories/base.py`.
2. Change the two constructor lines in `build_container()` in `backend/app.py`.

That is the whole change. Services, routes and tests are untouched, because
nothing above the repository layer knows SQLite exists. Records are already
stored in document shape — signals, rules and features as JSON — so they map onto
Cosmos documents directly.

---

## Testing conventions

Tests use the real trained artifacts, so model loading and inference are actually
exercised, but a temporary SQLite file per test, so runs never touch the
development database.

Fixtures in `conftest.py`:

| Fixture | Provides |
|---|---|
| `app`, `client` | Flask app and test client on a temp database |
| `container` | The service container, for testing services directly |
| `config` | A `Config` pointing at a temp database |
| `sample_payload` | An ordinary low-risk transaction |
| `known_fraud_payload` | A verbatim confirmed-fraud row from the dataset |
| `requires_model` | Skip marker for when artifacts are absent |

Two conventions worth keeping:

**Use real data for behavioural assertions.** `known_fraud_payload` is a genuine
fraud record rather than invented numbers, so the test asserts the model
recognises actual fraud. Hand-tuned vectors tend to assert only that the code
runs.

**Test the degraded paths.** `test_missing_artifacts_degrade_instead_of_crashing`
matters as much as the happy path: it pins the behaviour that the app starts and
reports its state when the model is missing, instead of dying at import.

---

## Common problems

**`ModuleNotFoundError: No module named 'ml'`**
Run from the project root with `python -m backend.app`, not
`python backend/app.py`.

**`/health` reports `model.loaded: false`**
`ml/artifacts/fraud_model.pkl` is missing or unreadable. The `error` field in the
health response gives the reason. Retrain with `python -m ml.train`.

**Scikit-learn version warning when loading the model**
Artifacts were pickled with the version pinned in `requirements.txt` (1.5.1).
Install the pinned version, or retrain to regenerate artifacts against yours.

**Training killed with no error message**
Out of memory. The SMOTE-resampled matrix is 453,204 × 30 and worker processes
duplicate it. Use `TRAIN_N_JOBS=1`.

**`database is locked`**
Concurrent writes to SQLite. WAL mode is enabled and connections are per-thread,
which handles the two Gunicorn workers; heavier concurrency is a reason to move
to the Cosmos repository rather than to tune SQLite.

**Frontend shows "Backend offline"**
The API is not running, or CORS is blocking. Opening `index.html` from disk uses
`file://` and falls back to `http://localhost:5000`; serving it through Flask
avoids the issue entirely.

---

## Before committing

```bash
pytest                                  # all 84 must pass
git status                              # .env must not appear
```

Check that no secret, no `.env`, no `creditcard.csv` and no `venv/` is staged.
`.gitignore` covers all four, but the original repository shipped `venv/` and a
144 MB CSV inside its archive, so the check is worth doing by hand.
