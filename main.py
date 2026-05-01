import pandas as pd
from zoneinfo import ZoneInfo


# LOAD DATA
# each csv becomes its own dataframe


user_referrals = pd.read_csv("data/user_referrals.csv")
user_referral_logs = pd.read_csv("data/user_referral_logs.csv")
user_logs = pd.read_csv("data/user_logs.csv")
user_referral_statuses = pd.read_csv("data/user_referral_statuses.csv")
referral_rewards = pd.read_csv("data/referral_rewards.csv")
paid_transactions = pd.read_csv("data/paid_transactions.csv")
lead_logs = pd.read_csv("data/lead_log.csv")


# DATA CLEANING
# fix data types so we can do math and comparisons on them


# reward_value is stored as "10 days", "15 days" etc — strip the text and convert to int
# so we can check if reward_value > 0 later in the fraud logic
referral_rewards["reward_value"] = (referral_rewards["reward_value"]
                                    .str.replace(" days", "", regex=False)
                                    .str.strip())
referral_rewards["reward_value"] = pd.to_numeric(
    referral_rewards["reward_value"], errors="coerce")

# convert timestamps — utc=True parses them as utc, then tz_localize(None)
# strips the timezone label so all datetimes are "naive" (no tz attached)
# this prevents the "cannot compare tz-naive and tz-aware" crash later
user_referrals["referral_at"] = pd.to_datetime(
    user_referrals["referral_at"], utc=True).dt.tz_localize(None)
user_referrals["updated_at"] = pd.to_datetime(
    user_referrals["updated_at"], utc=True).dt.tz_localize(None)

user_referral_logs["created_at"] = pd.to_datetime(
    user_referral_logs["created_at"], utc=True).dt.tz_localize(None)

user_logs["membership_expired_date"] = pd.to_datetime(
    user_logs["membership_expired_date"], utc=True).dt.tz_localize(None)

paid_transactions["transaction_at"] = pd.to_datetime(
    paid_transactions["transaction_at"], utc=True).dt.tz_localize(None)

# apply title case to name columns so values look clean in the report
# exception: homeclub stays as-is per the instructions
user_logs["name"] = user_logs["name"].str.title()
user_referrals["referee_name"] = user_referrals["referee_name"].str.title()


# DEDUPLICATION BEFORE JOINING
# some tables are "log" tables meaning they store a history of changes per record
# if we join without deduplicating, one referral matches many log rows = duplicate output rows


# user_logs has multiple rows per user_id (membership history)
# keep only the most recent record per user — the latest membership_expired_date
user_logs_clean = (user_logs
                   .sort_values("membership_expired_date", ascending=False)
                   .drop_duplicates(subset=["user_id"], keep="first")
                   )

# user_referral_logs has multiple entries per referral (audit trail)
# keep only the latest log entry per referral to get the final reward status
user_referral_logs_clean = (user_referral_logs
                            .sort_values("created_at", ascending=False)
                            .drop_duplicates(subset=["user_referral_id"], keep="first")
                            )


# TIMEZONE CONVERSION
# all timestamps are stored in utc — convert to local time using each row's timezone column


def convert_utc_to_local(dt, timezone_str):
    # if either value is missing just return the original datetime unchanged
    if pd.isnull(dt) or pd.isnull(timezone_str):
        return dt
    try:
        # attach utc label so python knows what to convert FROM
        dt_aware = dt.replace(tzinfo=ZoneInfo("UTC"))
        # convert to local time then strip the timezone label so it's naive again
        return dt_aware.astimezone(ZoneInfo(timezone_str)).replace(tzinfo=None)
    except Exception:
        return dt


# each transaction has its own timezone_transaction column
paid_transactions["transaction_at_local"] = paid_transactions.apply(
    lambda row: convert_utc_to_local(
        row["transaction_at"], row["timezone_transaction"]),
    axis=1
)


# JOIN TABLES
# merge all tables together like vlookup in excel
# always use how="left" so we keep all 46 referral rows even if a match is missing


# start with user_referrals as the base — it has exactly 46 rows (one per referral)
# add referral status description e.g. maps status id 2 → "Berhasil"
df = user_referrals.merge(
    user_referral_statuses[["id", "description"]].rename(
        columns={"description": "referral_status"}),
    left_on="user_referral_status_id",
    right_on="id",
    how="left"
)

# add referrer info (the person who sent the referral code)
# use the deduplicated user_logs so one user_id maps to exactly one row
df = df.merge(
    user_logs_clean[["user_id", "name", "phone_number",
                     "homeclub", "membership_expired_date", "is_deleted"]],
    left_on="referrer_id",
    right_on="user_id",
    how="left",
    suffixes=("", "_referrer")
)

# add reward info — what reward was offered for this referral
df = df.merge(
    referral_rewards[["id", "reward_value", "reward_type"]].rename(
        columns={"id": "reward_id"}),
    left_on="referral_reward_id",
    right_on="reward_id",
    how="left"
)

# add transaction info — the actual paid transaction linked to this referral
df = df.merge(
    paid_transactions,
    on="transaction_id",
    how="left"
)

# add referral log info — whether the reward was granted and when
# use the deduplicated logs so one referral maps to exactly one log row
df = df.merge(
    user_referral_logs_clean[["user_referral_id", "is_reward_granted", "created_at"]].rename(
        columns={"created_at": "reward_granted_at"}),
    left_on="referral_id",
    right_on="user_referral_id",
    how="left"
)

# for Lead source referrals, pull source_category from lead_logs
# other referral sources already know their category (Online/Offline)
lead_source = lead_logs[["lead_id", "source_category"]].drop_duplicates()
df = df.merge(lead_source, left_on="referee_id",
              right_on="lead_id", how="left")


# DATA PROCESSING
# derive new columns from existing data


# map referral_source to a human-readable category
# Lead referrals inherit their category directly from lead_logs.source_category


def get_source_category(row):
    if row["referral_source"] == "User Sign Up":
        return "Online"
    elif row["referral_source"] == "Draft Transaction":
        return "Offline"
    elif row["referral_source"] == "Lead":
        return row["source_category"]
    return None


df["referral_source_category"] = df.apply(get_source_category, axis=1)


# FRAUD DETECTION
# apply business logic rules to flag valid vs invalid referral rewards
# result stored in is_business_logic_valid (True = valid, False = fraud/invalid)


def is_valid(row):
    # pull values out of the row safely
    status = row.get("referral_status", "")
    reward_value = row.get("reward_value", None)
    transaction_id = row.get("transaction_id", None)
    transaction_status = str(row.get("transaction_status", "")).upper()
    transaction_type = str(row.get("transaction_type", "")).upper()
    transaction_at = row.get("transaction_at_local")
    referral_at = row.get("referral_at")
    membership_expired = row.get("membership_expired_date")
    is_deleted = row.get("is_deleted", True)
    is_reward_granted = row.get("is_reward_granted", False)

    # safely convert reward_value to float — won't crash on null or string values
    try:
        reward_value = float(reward_value) if pd.notnull(
            reward_value) else None
    except (ValueError, TypeError):
        reward_value = None

    # helper booleans used throughout the checks below
    has_reward = reward_value is not None and reward_value > 0
    has_transaction = pd.notnull(transaction_id)

    # safely compute date comparisons — wrapped in try/except so nulls don't crash
    try:
        tx_after_referral = (pd.notnull(transaction_at)
                             and pd.notnull(referral_at)
                             and transaction_at > referral_at)
        same_month = (pd.notnull(transaction_at)
                      and pd.notnull(referral_at)
                      and transaction_at.month == referral_at.month
                      and transaction_at.year == referral_at.year)
        tx_before_referral = (pd.notnull(transaction_at)
                              and pd.notnull(referral_at)
                              and transaction_at < referral_at)
    except Exception:
        tx_after_referral = False
        same_month = False
        tx_before_referral = False

    # safely check membership — null means no expiry on record (treat as valid)
    try:
        membership_valid = (pd.isnull(membership_expired)
                            or (pd.notnull(referral_at)
                                and membership_expired > referral_at))
    except Exception:
        membership_valid = True

    #  valid condition 1
    # successful referral where all integrity checks pass
    if (has_reward
            and status == "Berhasil"
            and has_transaction
            and transaction_status == "PAID"
            and transaction_type == "NEW"
            and tx_after_referral
            and same_month
            and membership_valid
            and not is_deleted
            and is_reward_granted):
        return True

    #  valid condition 2
    # pending or failed referral with no reward assigned — expected and fine
    if status in ("Menunggu", "Tidak Berhasil") and not has_reward:
        return True

    #  invalid condition 1
    # reward was given but the referral status is not successful
    if has_reward and status != "Berhasil":
        return False

    #  invalid condition 2
    # reward was given but there is no transaction linked to this referral
    if has_reward and not has_transaction:
        return False

    #  invalid condition 3
    # no reward but there is a paid transaction after the referral — reward was missed
    if (not has_reward
            and has_transaction
            and transaction_status == "PAID"
            and tx_after_referral):
        return False

    #  invalid condition 4
    # referral succeeded but no reward was assigned
    if status == "Berhasil" and not has_reward:
        return False

    #  invalid condition 5
    # transaction happened before the referral was created — impossible, likely fraud
    if tx_before_referral:
        return False

    return True  # default — no fraud flags triggered


df["is_business_logic_valid"] = df.apply(is_valid, axis=1)

# OUTPUT
# select and rename columns to match the required report format

output_cols = {
    "referral_id": "referral_id",
    "referral_source": "referral_source",
    "referral_source_category": "referral_source_category",
    "referral_at": "referral_at",
    "referrer_id": "referrer_id",
    "name": "referrer_name",
    "phone_number": "referrer_phone_number",
    "homeclub": "referrer_homeclub",
    "referee_id": "referee_id",
    "referee_name": "referee_name",
    "referee_phone": "referee_phone",
    "referral_status": "referral_status",
    "reward_value": "num_reward_days",
    "transaction_id": "transaction_id",
    "transaction_status": "transaction_status",
    "transaction_at_local": "transaction_at",
    "transaction_location": "transaction_location",
    "transaction_type": "transaction_type",
    "updated_at": "updated_at",
    "reward_granted_at": "reward_granted_at",
    "is_business_logic_valid": "is_business_logic_valid",
}

report = df[list(output_cols.keys())].rename(columns=output_cols)

# add sequential id starting at 101 as required by the test spec
report.insert(0, "referral_details_id", range(101, 101 + len(report)))

# remove any duplicates and rows with no referral id
report = report.drop_duplicates().dropna(subset=["referral_id"])

report.to_csv("output/referral_report.csv", index=False)
print(f"Report saved — {len(report)} rows")
