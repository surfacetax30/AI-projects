import os
import sys
import tempfile


TEMP_DB = os.path.join(tempfile.mkdtemp(prefix="ots_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEMP_DB}"