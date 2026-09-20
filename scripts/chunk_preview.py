"""
Print the shape of the first few chunks of the raw order_items export.

    python scripts/chunk_preview.py

Needs data/order_items.csv, the large source file, which is gitignored.
Renamed out of src/: the old name chunk_test.py matched pytest's discovery
pattern, so collecting the suite failed on the missing CSV.
"""

import pandas as pd

chunks = pd.read_csv(
    "data/order_items.csv",
    chunksize=100_000
)

for i, chunk in enumerate(chunks):
    print(f"Chunk {i + 1}: {chunk.shape}")

    if i == 2:
        break