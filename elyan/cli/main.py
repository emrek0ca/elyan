from cli.main import main as _legacy_main


def main(argv: list[str] | None = None):
    return _legacy_main(argv)


run = main

__all__ = ["main", "run"]


if __name__ == "__main__":
    raise SystemExit(main())

