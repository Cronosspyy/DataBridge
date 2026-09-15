import pandas as pd

N_ORDERS = 5000

# -----------------------------
# 1. Select orders
# -----------------------------
orders = pd.read_csv("data/orders.csv")

selected_orders = orders.sample(
    n=N_ORDERS,
    random_state=42
)

order_ids = set(selected_orders["order_id"])

print("Selected orders:", len(selected_orders))


# -----------------------------
# 2. Select customers
# -----------------------------
customers = pd.read_csv("data/customers.csv")

customer_ids = selected_orders["customer_id"].unique()

selected_customers = customers[
    customers["customer_id"].isin(customer_ids)
]

print("Selected customers:", len(selected_customers))


# -----------------------------
# 3. Select matching order_items
# -----------------------------
selected_items = []

print("\nReading order_items in chunks...")

for chunk in pd.read_csv(
    "data/order_items.csv",
    chunksize=100_000
):
    matching = chunk[
        chunk["order_id"].isin(order_ids)
    ]

    if len(matching) > 0:
        selected_items.append(matching)

    print(f"Processed chunk: {len(chunk)} rows")


# Combine matching items
selected_order_items = pd.concat(
    selected_items,
    ignore_index=True
)

print("\nSelected order_items:", len(selected_order_items))


# -----------------------------
# 4. Save selected data
# -----------------------------
selected_orders.to_csv(
    "data/selected_orders.csv",
    index=False
)

selected_customers.to_csv(
    "data/selected_customers.csv",
    index=False
)

selected_order_items.to_csv(
    "data/selected_order_items.csv",
    index=False
)

print("\nSaved:")
print("data/selected_orders.csv")
print("data/selected_customers.csv")
print("data/selected_order_items.csv")

# ------------------------------
# 4. Select products
# ------------------------------

selected_order_items = pd.read_csv("data/selected_order_items.csv")

product_ids = set(selected_order_items["product_id"])

products = pd.read_csv("data/products.csv")

selected_products = products[
    products["product_id"].isin(product_ids)
]

selected_products.to_csv(
    "data/selected_products.csv",
    index=False
)

print("Unique products:", len(product_ids))
print("Selected products:", len(selected_products))

print("\nSaved:")
print("data/selected_products.csv")