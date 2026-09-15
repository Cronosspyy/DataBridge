import pandas as pd

# Number of orders we want
N_ORDERS = 5000

# Read orders
orders = pd.read_csv("data/orders.csv")

# Select 5000 orders
selected_orders = orders.sample(
    n=N_ORDERS,
    random_state=42
)

# Get the customer IDs connected to these orders
customer_ids = selected_orders["customer_id"].unique()

print("Selected orders:", len(selected_orders))
print("Unique customers:", len(customer_ids))

# Read customers
customers = pd.read_csv("data/customers.csv")

# Keep only customers belonging to our selected orders
selected_customers = customers[
    customers["customer_id"].isin(customer_ids)
]

print("Selected customers:", len(selected_customers))

# Save the selected data
selected_orders.to_csv(
    "data/selected_orders.csv",
    index=False
)

selected_customers.to_csv(
    "data/selected_customers.csv",
    index=False
)

print("\nSaved:")
print("data/selected_orders.csv")
print("data/selected_customers.csv")