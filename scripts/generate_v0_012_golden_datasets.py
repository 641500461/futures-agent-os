"""Regenerate the committed V0-012 synthetic golden fixture deterministically."""

from futures_agent_os.reference_market_data.golden_datasets import repository_dataset_root, write_golden_dataset


if __name__ == "__main__":
    write_golden_dataset(repository_dataset_root())
