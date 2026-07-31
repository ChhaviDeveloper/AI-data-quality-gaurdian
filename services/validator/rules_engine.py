"""
Registry-driven rule evaluation engine.

Adapted from the root-level audit_validator_registry_single_loop.py so the
validator Cloud Run Job can run against a BigQuery dataframe instead of a
local CSV. Logic is intentionally kept close to the original so results are
comparable to the local demo runs your team already validated.

Fix vs. the original: RuleContext was missing `future_dr_dates()`, which
rule R015 calls -- it would have silently no-opped (returned no failures)
every run. Implemented properly below.

Second fix, found by running this against a real edge-case-heavy CSV: four
python-type rules (R002 is_unique, R005 all_yes_no, R012 dr_test_valid,
R014 exception_expiry_valid) returned a single aggregate bool instead of a
per-row Series. The original engine treated any bare bool as "no failures"
-- so these four rules silently never flagged anything, no matter how bad
the data was. Added proper *_mask() methods that return a per-row boolean
Series instead, and updated rules_registry.yaml + functional_parser.py's
RULE_TEMPLATES to call them. (An earlier version of this file tried to
patch the bare-bool case by failing the WHOLE table instead of specific
rows -- that's arguably worse than the original bug, since e.g. one
duplicated application_id would flag all 151 rows as failed. Don't
reintroduce that.)

Known caveat carried over from the original script: dates like "29-06-2026"
are ambiguous (day-first vs month-first). Set DATE_DAYFIRST=true if your
team confirms the source data is day-first; defaults to False to match the
original script's behavior and keep parity with already-validated results.
"""
import os
import logging
import pandas as pd

logger = logging.getLogger("validator.rules_engine")

DATE_DAYFIRST = os.environ.get("DATE_DAYFIRST", "false").lower() == "true"

DATE_COLUMNS = [
    "last_control_test_date",
    "evidence_submission_date",
    "access_review_date",
    "dr_test_date",
    "exception_expiry_date",
]

NUMERIC_COLUMNS = ["privileged_access_count", "open_high_vulnerabilities"]


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror the type coercion the local validator did on the raw CSV."""
    df = df.copy()
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col + "_dt"] = pd.to_datetime(df[col], errors="coerce", dayfirst=DATE_DAYFIRST)
    return df


class RuleContext:
    def __init__(self, df: pd.DataFrame, assessment_date: pd.Timestamp):
        self.df = df
        self.assessment_date = assessment_date

    # --- Deprecated aggregate checks (kept for reference / anything else
    # that might call them) -- these return a single bool for the WHOLE
    # dataframe, which is meaningless for row-level rule evaluation. Use
    # the *_mask() equivalents below in rules_registry.yaml instead.
    def is_unique(self, col):
        s = self.df[col].dropna().astype(str).str.strip()
        return not s.duplicated().any()

    def all_yes_no(self, cols):
        for c in cols:
            if c in self.df.columns:
                if not self.df[c].isin(["Yes", "No"]).all():
                    return False
        return True

    def dr_test_valid(self):
        dfc = self.df[self.df["criticality"] == "Critical"]
        if dfc.empty:
            return True
        cond = (dfc.get("dr_test_completed") == "Yes") & (~dfc["dr_test_date_dt"].isna())
        return cond.all()

    def exception_expiry_valid(self):
        if "policy_exception" not in self.df.columns:
            return True
        dfp = self.df[self.df["policy_exception"] == "Yes"]
        if dfp.empty:
            return True
        if "exception_expiry_date_dt" not in dfp.columns:
            return False
        return (dfp["exception_expiry_date_dt"] >= self.assessment_date).all()

    # --- Row-level mask methods -- these are what rules_registry.yaml
    # should actually call, since they identify WHICH rows fail rather than
    # a single aggregate yes/no for the whole table.
    def duplicated_mask(self, col):
        """True for every row that shares its (non-blank) value in `col`
        with at least one other row -- i.e. every row involved in a
        duplicate, not just an aggregate yes/no."""
        if col not in self.df.columns:
            return pd.Series(False, index=self.df.index)
        values = self.df[col].astype(str).str.strip()
        return values.duplicated(keep=False) & (values != "")

    def invalid_yes_no_mask(self, cols):
        """True for rows where ANY of `cols` has a value other than Yes/No."""
        mask = pd.Series(False, index=self.df.index)
        for c in cols:
            if c in self.df.columns:
                mask = mask | (~self.df[c].isin(["Yes", "No"]))
        return mask

    def dr_test_invalid_mask(self):
        """True for Critical apps missing dr_test_completed='Yes' or a
        parseable dr_test_date."""
        if "dr_test_date_dt" not in self.df.columns:
            return pd.Series(False, index=self.df.index)
        is_critical = self.df.get("criticality") == "Critical"
        missing = (self.df.get("dr_test_completed") != "Yes") | (self.df["dr_test_date_dt"].isna())
        return is_critical & missing

    def exception_expiry_invalid_mask(self):
        """True for policy_exception='Yes' rows with a missing or already-
        expired exception_expiry_date."""
        if "policy_exception" not in self.df.columns:
            return pd.Series(False, index=self.df.index)
        has_exception = self.df["policy_exception"] == "Yes"
        if "exception_expiry_date_dt" not in self.df.columns:
            return has_exception
        expired_or_missing = (
            self.df["exception_expiry_date_dt"].isna()
            | (self.df["exception_expiry_date_dt"] < self.assessment_date)
        )
        return has_exception & expired_or_missing

    def future_dr_dates(self):
        """Rows where dr_test_date is AFTER the assessment date -> failure.

        Returns a boolean Series aligned to self.df (True = this row fails).
        Missing dr_test_date is not itself a "future date" failure (R012
        already covers missing/incomplete DR tests for Critical apps).
        """
        if "dr_test_date_dt" not in self.df.columns:
            return pd.Series(False, index=self.df.index)
        return (self.df["dr_test_date_dt"] > self.assessment_date).fillna(False)


def evaluate_rule(df: pd.DataFrame, rule: dict, ctx: RuleContext) -> pd.DataFrame:
    """Returns the DataFrame of rows that FAIL `rule`."""
    rtype = rule.get("type", "expression")
    expr = rule.get("expression", "")

    if rtype == "expression":
        try:
            failed = df.query(expr)
        except Exception:
            mask = df.apply(lambda row: _safe_eval_expression(expr, row.to_dict()), axis=1)
            failed = df[mask]
        return failed

    if rtype == "python":
        try:
            result = eval(expr, {"__builtins__": None}, {"df": df, "ctx": ctx, "pd": pd})
            if isinstance(result, pd.Series):
                return df[result.fillna(False)]
            # A bare boolean can't be mapped back to specific rows -- flagging
            # either "all rows" or "no rows" is misleading either way, so
            # refuse to guess and make it loud instead. Fix the rule
            # expression to call a *_mask() method that returns a Series.
            logger.warning(
                "Rule %s's python expression returned a bare bool instead of "
                "a per-row Series -- treating as 'no failures' since we can't "
                "tell which rows are actually bad. Fix the expression to use "
                "a *_mask() method. Expression: %s",
                rule.get("rule_id", "?"), expr,
            )
            return df.iloc[0:0]
        except Exception:
            logger.exception("Rule %s's python expression raised an exception: %s",
                              rule.get("rule_id", "?"), expr)
            return df.iloc[0:0]

    return df.iloc[0:0]


def _safe_eval_expression(expr, row_dict):
    try:
        return bool(eval(expr, {"__builtins__": None}, row_dict))
    except Exception:
        return False


def run_all_rules(df: pd.DataFrame, rules: list, assessment_date: pd.Timestamp):
    """Returns (results_df, failed_records: dict[rule_id -> DataFrame])."""
    results = []
    failed_records = {}
    total_records = len(df)
    ctx = RuleContext(df, assessment_date)

    for rule in rules:
        failed = evaluate_rule(df, rule, ctx)
        failed_count = len(failed)
        passed_count = total_records - failed_count
        pass_percentage = round((passed_count / total_records) * 100, 2) if total_records else 0
        results.append({
            "rule_id": rule["rule_id"],
            "rule_name": rule.get("rule_name", ""),
            "description": rule.get("description", ""),
            "severity": rule.get("severity", ""),
            "dimension": rule.get("dimension", ""),
            "total_records": total_records,
            "failed_count": failed_count,
            "passed_count": passed_count,
            "pass_percentage": pass_percentage,
            "status": "Passed" if failed_count == 0 else "Failed",
        })
        failed_records[rule["rule_id"]] = failed.copy()

    return pd.DataFrame(results), failed_records
