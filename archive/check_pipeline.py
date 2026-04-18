import pandas as pd

df = pd.read_csv("bt_history.csv")

print("\n=== PIPELINE HEALTH CHECK ===")

print("\nRows:", len(df))

if "emissions" in df.columns:
    print("Emissions sample:", df["emissions"].tail(3).tolist())
else:
    print("❌ Missing column: emissions")

if "flow_24h" in df.columns:
    print("Flow sample:", df["flow_24h"].tail(3).tolist())
else:
    print("❌ Missing column: flow_24h")

if "apr" in df.columns:
    print("APR sample:", df["apr"].tail(3).tolist())
else:
    print("❌ Missing column: apr")

print("\nLatest timestamp:", df.iloc[-1].to_dict())