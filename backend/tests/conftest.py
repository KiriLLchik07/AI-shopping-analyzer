from pathlib import Path
from dotenv import load_dotenv


TESTS_ROOT = Path(__file__).resolve().parent
load_dotenv(TESTS_ROOT / ".env.test", override=True)
