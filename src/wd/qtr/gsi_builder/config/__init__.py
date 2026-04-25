import os

# Determine if running in Unity Catalog environment.
running_as_uc = os.getenv("DATABRICKS_RUNTIME_VERSION") is not None
