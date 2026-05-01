import pandas as pd
import os

csv_files = {
    "user_referrals": "data/user_referrals.csv",
    "user_referral_logs": "data/user_referral_logs.csv",
    "user_logs": "data/user_logs.csv",
    "user_referral_statuses": "data/user_referral_statuses.csv",
    "referral_rewards": "data/referral_rewards.csv",
    "paid_transactions": "data/paid_transactions.csv",
    "lead_logs": "data/lead_logs.csv",
}

results = []

for table_name, path in csv_files.items():
    df = pd.read_csv(path)  # load csv into a dataframe

    for col in df.columns:  # loop through every column
        results.append({
            "table": table_name,
            "column": col,
            "data_type": str(df[col].dtype),
            "null_count": df[col].isnull().sum(),  # how many blanks
            "distinct_count": df[col].nunique(),    # how many unique values
            "sample_value": df[col].dropna().iloc[0] if not df[col].dropna().empty else None
        })


# saves to excel
profile_df = pd.DataFrame(results)
profile_df.to_excel("output/data_profiling.xlsx", index=False)
print("Profiling done!")
