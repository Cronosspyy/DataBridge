import pandas as pd

chunks = pd.read_csv(
    "data/order_items.csv",
    chunksize=100_000
)

for i, chunk in enumerate(chunks):
    print(f"Chunk {i + 1}: {chunk.shape}")

    if i == 2:
        break